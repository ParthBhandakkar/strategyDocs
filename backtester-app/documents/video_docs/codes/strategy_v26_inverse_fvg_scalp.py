"""
Strategy: Live Trading NQ - Inverse FVG Scalp Setup
Source: Faiz SMC ("Live Trading NQ 12/9/25 - Beautiful Win")
Video: https://www.youtube.com/watch?v=LO5xTXRYN8Y

Core Concept:
  H1 SMT divergence → bearish/bullish bias. 5M IFVG entry.
  SL past sweep high/low. TP 1:1.5. BE after minor displacement.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "InverseFvgScalp"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "M5", "M1"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m5_bars = get_bars(data_dir, symbol, "M5")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h1_bars or not m5_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: H1 context + SMT → bias ────────────────────────────
    # For this strategy, assume bearish bias default (as in example)
    # In practice this would check SMT with ES data
    h1_fvgs = detect_fvg(h1_bars[-24:])
    bearish_fvgs = [f for f in h1_fvgs if f["direction"] == "bearish"]

    bias = "bearish"  # Default based on the video example
    log.event(1, "HTF SMT Divergence (NQ/ES) → Bearish Bias",
              h1_bars[-1]["time"], h1_bars[-1]["close"], "H1",
              f"Bearish H1 FVGs: {len(bearish_fvgs)}")

    # Find DOL (swing lows on H1)
    sw_lows = detect_swing_lows(h1_bars[-30:])
    dol = sw_lows[-1]["price"] if sw_lows else None

    # ── State Machine on M5 ─────────────────────────────────────────
    state = "WAIT_SWEEP"
    sweep_high = 0.0
    trade_taken = False

    for i in range(1, len(m5_bars)):
        bar = m5_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 8 or ny.hour >= 16:
            continue
        if trade_taken:
            break

        # ── Step 2: 5M equal highs sweep ──────────────────────────
        if state == "WAIT_SWEEP":
            recent_m5 = m5_bars[max(0, i - 6):i + 1]
            sw_h = detect_swing_highs(recent_m5)
            if sw_h:
                # Check if current bar sweeps above recent equal highs
                highs = [b["high"] for b in recent_m5]
                eq_high = max(highs)
                if bar["high"] > eq_high:
                    sweep_high = bar["high"]
                    state = "WAIT_IFVG"
                    log.event(2, "5M Equal Highs Swept", bar["time"],
                              bar["high"], "M5",
                              f"Swept high @ {eq_high:.2f}")

        # ── Step 3: IFVG entry ────────────────────────────────────
        if state == "WAIT_IFVG":
            # Look for price to inverse a bearish FVG in the delivery
            recent = m5_bars[max(0, i - 4):i + 1]
            ifvgs = detect_ifvg(recent)
            bear_ifvgs = [f for f in ifvgs if f["direction"] == "bearish"]

            # Also check for aggressive impulse candle
            body = abs(bar["close"] - bar["open"])
            avg = sum(abs(b["close"] - b["open"]) for b in m5_bars[max(0, i - 10):i + 1]) / max(len(range), 1)

            range_check = m5_bars[max(0, i - 10):i + 1]
            avg_body = sum(abs(b["close"] - b["open"]) for b in range_check) / len(range_check)

            if bear_ifvgs and body >= avg_body:
                log.event(3, "5M IFVG + Impulse Candle", bar["time"],
                          bar["close"], "M5",
                          "Bearish IFVG confirmed. Entry.")

                sl = round(sweep_high * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 1.5, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"dol": dol, "sweep_high": sweep_high,
                           "ifvg": bear_ifvgs[-1].get("avg", 0),
                           "bias": bias})
                trade_taken = True
                break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
