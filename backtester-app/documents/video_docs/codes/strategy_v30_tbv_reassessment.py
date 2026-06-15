"""
Strategy: 3-Step Time-Based Volume (TBV) Reassessment Model
Source: Faiz SMC ("My 80% Winrate 3-Step Trading Strategy That Works!")
Video: https://www.youtube.com/watch?v=wpvzFFN3pDo

Core Concept:
  TBV on 5M/15M/H1. FVG + swing point inside → sweep + absorption close.
  3 entry techniques: (A) market at close, (B) 50% limit, (C) open retest.
  TP = -2.0 fib extension. Same-TF execution.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "TBVReassessment"
SYMBOL = "NQ"
TIMEFRAMES = ["M5", "M15", "H1"]


def detect_swing_3candle(bars: list) -> list:
    """Return list of valid 3-candle swing highs and lows."""
    swings = []
    for i in range(1, len(bars) - 1):
        c = bars[i]
        p = bars[i - 1]
        n = bars[i + 1]
        if c["low"] < p["low"] and c["low"] < n["low"]:
            swings.append({"type": "low", "price": c["low"], "time": c["time"], "index": i})
        if c["high"] > p["high"] and c["high"] > n["high"]:
            swings.append({"type": "high", "price": c["high"], "time": c["time"], "index": i})
    return swings


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    # Default to M5 (primary TF for this strategy)
    bars = get_bars(data_dir, symbol, "M5")
    if not bars:
        print("No data found")
        return

    # ── State Machine ───────────────────────────────────────────────
    state = "WAIT_FVG"
    current_fvg = None
    current_swing = None
    sweep_idx = 0
    trade_taken = False

    for i in range(3, len(bars)):
        bar = bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 7 or ny.hour >= 16:
            continue
        if trade_taken:
            break

        # ── Step 1-2: FVG + swing point ──────────────────────────
        if state == "WAIT_FVG":
            recent = bars[max(0, i - 8):i + 1]
            fvgs = detect_fvg(recent)
            if not fvgs:
                continue

            swings = detect_swing_3candle(bars[max(0, i - 6):i + 2])

            for f in fvgs:
                for sw in swings:
                    if f["bottom"] <= sw["price"] <= f["top"]:
                        current_fvg = f
                        current_swing = sw
                        state = "WAIT_SWEEP"
                        log.event(1, f"FVG + Swing {sw['type'].upper()} Inside",
                                  bar["time"], sw["price"], "M5",
                                  f"Swing @ {sw['price']:.2f} in "
                                  f"FVG {f['bottom']:.2f}-{f['top']:.2f}")
                        break
                if state == "WAIT_SWEEP":
                    break

        # ── Step 3: Sweep + absorption close ─────────────────────
        if state == "WAIT_SWEEP" and current_swing and current_fvg:
            sweep_occurred = False
            if current_swing["type"] == "low" and bar["low"] < current_swing["price"]:
                # Check FVG boundary invalidation
                fvg_candle1_low = bars[i - 2]["low"] if i >= 2 else 0
                if bar["low"] < fvg_candle1_low:
                    log.event(2, "Invalid: Swept below FVG candle 1 low",
                              bar["time"], bar["low"], "M5")
                    state = "WAIT_FVG"
                    continue

                # Check in-FVG
                in_fvg = (current_fvg["bottom"] <= bar["high"] and
                          current_fvg["top"] >= bar["low"])
                if not in_fvg:
                    continue

                # Absorption: bullish close
                if bar["close"] > bar["open"]:
                    sweep_idx = i
                    log.event(2, "Bullish Absorption (Swept Low)", bar["time"],
                              bar["close"], "M5",
                              f"Absorption confirmed. Entry options: "
                              f"(A) Market @ close, (B) 50% retrace, "
                              f"(C) Open price retest.")

                    # Entry Technique A: Aggressive
                    entry_a = bar["close"]
                    sl = round(bar["low"] * 0.9998, 5)
                    tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                    fib_50 = (bar["high"] + bar["low"]) / 2
                    entry_b = round(fib_50, 5)
                    entry_c = round(bar["open"], 5)

                    log.trade("LONG", entry_a, sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"entry_technique": "A - Market @ Close",
                               "fvg_top": current_fvg["top"],
                               "fvg_bottom": current_fvg["bottom"],
                               "swing_low": current_swing["price"],
                               "sweep_low": bar["low"],
                               "entry_b_50pct": entry_b,
                               "entry_c_open": entry_c,
                               "tp_note": "-2.0 fib target"})
                    trade_taken = True
                    break
                else:
                    log.event(2, "Invalid: Swept low but bearish close",
                              bar["time"], bar["close"], "M5")
                    state = "WAIT_FVG"
                    continue

            elif current_swing["type"] == "high" and bar["high"] > current_swing["price"]:
                fvg_candle1_high = bars[i - 2]["high"] if i >= 2 else 0
                if bar["high"] > fvg_candle1_high:
                    log.event(2, "Invalid: Swept above FVG candle 1 high",
                              bar["time"], bar["high"], "M5")
                    state = "WAIT_FVG"
                    continue

                in_fvg = (current_fvg["bottom"] <= bar["high"] and
                          current_fvg["top"] >= bar["low"])
                if not in_fvg:
                    continue

                if bar["close"] < bar["open"]:
                    sweep_idx = i
                    log.event(2, "Bearish Absorption (Swept High)", bar["time"],
                              bar["close"], "M5",
                              f"Absorption confirmed.")

                    entry_a = bar["close"]
                    sl = round(bar["high"] * 1.0002, 5)
                    tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                    fib_50 = (bar["high"] + bar["low"]) / 2
                    entry_b = round(fib_50, 5)
                    entry_c = round(bar["open"], 5)

                    log.trade("SHORT", entry_a, sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"entry_technique": "A - Market @ Close",
                               "fvg_top": current_fvg["top"],
                               "fvg_bottom": current_fvg["bottom"],
                               "swing_high": current_swing["price"],
                               "sweep_high": bar["high"],
                               "entry_b_50pct": entry_b,
                               "entry_c_open": entry_c,
                               "tp_note": "-2.0 fib target"})
                    trade_taken = True
                    break
                else:
                    log.event(2, "Invalid: Swept high but bullish close",
                              bar["time"], bar["close"], "M5")
                    state = "WAIT_FVG"
                    continue

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
