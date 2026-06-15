"""
Strategy: Time-Based Volume (TBV) Core Strategy
Source: Faiz SMC ("Give Me 9 Minutes & I'll Teach You My 80% Winrate Trading Strategy")
Video: https://www.youtube.com/watch?v=6HMG-NO2h_A

Core Concept:
  3M+ timeframe (never 1M/2M). Same-TF FVG + swing point inside/near FVG.
  Candle sweeps swing point → closes as absorption (bullish after low sweep,
  bearish after high sweep). Enter at close. SL past sweep wick. TP 1:2.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "TimeBasedVolumeTBV"
SYMBOL = "NQ"
TIMEFRAMES = ["M3", "M5", "M15"]


def detect_swing_low_3candle(bars: list, idx: int) -> dict | None:
    """3-candle swing low: center candle lower low than neighbors."""
    if idx < 1 or idx >= len(bars) - 1:
        return None
    c = bars[idx]
    p = bars[idx - 1]
    n = bars[idx + 1]
    if c["low"] < p["low"] and c["low"] < n["low"]:
        return {"index": idx, "price": c["low"], "time": c["time"]}
    return None


def detect_swing_high_3candle(bars: list, idx: int) -> dict | None:
    """3-candle swing high: center candle higher high than neighbors."""
    if idx < 1 or idx >= len(bars) - 1:
        return None
    c = bars[idx]
    p = bars[idx - 1]
    n = bars[idx + 1]
    if c["high"] > p["high"] and c["high"] > n["high"]:
        return {"index": idx, "price": c["high"], "time": c["time"]}
    return None


def find_fvg_near_swing(bars: list, swing_price: float, fvg: dict) -> bool:
    """Check if FVG contains or is near the swing point."""
    return fvg["bottom"] <= swing_price <= fvg["top"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    # Use M3 as primary (as per strategy)
    bars = get_bars(data_dir, symbol, "M3")
    if not bars:
        print("No M3 data found")
        return

    # ── State Machine ───────────────────────────────────────────────
    state = "WAIT_FVG"
    current_fvg = None
    current_swing = None
    swing_type = None
    trade_taken = False

    for i in range(3, len(bars) - 1):
        bar = bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 7 or ny.hour >= 16:
            continue
        if trade_taken:
            break

        # ── Step 2-3: Same-TF FVG + identify swing ───────────────
        if state == "WAIT_FVG":
            # Detect FVGs in recent bars
            recent = bars[max(0, i - 6):i + 1]
            fvgs = detect_fvg(recent)
            if not fvgs:
                continue

            # For each FVG, find a swing inside or near it
            for f in fvgs:
                # Check for swing low inside FVG
                for j in range(max(1, i - 4), min(len(bars) - 1, i + 2)):
                    sw_low = detect_swing_low_3candle(bars, j)
                    if sw_low and f["bottom"] <= sw_low["price"] <= f["top"]:
                        current_fvg = f
                        current_swing = sw_low
                        swing_type = "low"
                        state = "WAIT_SWEEP"
                        log.event(1, "FVG + Swing Low Inside", bar["time"],
                                  sw_low["price"], "M3",
                                  f"Swing low @ {sw_low['price']:.2f} in "
                                  f"FVG {f['bottom']:.2f}-{f['top']:.2f}")
                        break

                    sw_high = detect_swing_high_3candle(bars, j)
                    if sw_high and f["bottom"] <= sw_high["price"] <= f["top"]:
                        current_fvg = f
                        current_swing = sw_high
                        swing_type = "high"
                        state = "WAIT_SWEEP"
                        log.event(1, "FVG + Swing High Inside", bar["time"],
                                  sw_high["price"], "M3",
                                  f"Swing high @ {sw_high['price']:.2f} in "
                                  f"FVG {f['bottom']:.2f}-{f['top']:.2f}")
                        break

                if state == "WAIT_SWEEP":
                    break

        # ── Step 4: Sweep + absorption close ─────────────────────
        if state == "WAIT_SWEEP" and current_swing and current_fvg:
            # Check if this candle sweeps the swing point
            if swing_type == "low" and bar["low"] < current_swing["price"]:
                # Must also be in/around the FVG
                in_fvg = (current_fvg["bottom"] <= bar["high"] and
                          bar["low"] <= current_fvg["top"])
                if not in_fvg:
                    if bar["high"] < current_fvg["bottom"] or bar["low"] > current_fvg["top"]:
                        # Swept clean past FVG → invalidate
                        log.event(2, "Invalid: Swept outside FVG", bar["time"],
                                  bar["close"], "M3")
                        state = "WAIT_FVG"
                        continue

                # Step 5: Check absorption close (bullish close)
                if bar["close"] > bar["open"]:
                    log.event(2, "Bullish Absorption Candle", bar["time"],
                              bar["close"], "M3",
                              f"Swept low @ {current_swing['price']:.2f}, "
                              f"closed bullish.")

                    sl = round(bar["low"] * 0.9998, 5)
                    tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                    log.trade("LONG", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"fvg_top": current_fvg["top"],
                               "fvg_bottom": current_fvg["bottom"],
                               "swing_low": current_swing["price"],
                               "setup_type": "TBV Absorption"})
                    trade_taken = True
                    break
                else:
                    # First candle swept but closed bearish → invalid
                    log.event(2, "Invalid: Swept low but closed bearish",
                              bar["time"], bar["close"], "M3")
                    state = "WAIT_FVG"
                    continue

            elif swing_type == "high" and bar["high"] > current_swing["price"]:
                in_fvg = (current_fvg["bottom"] <= bar["high"] and
                          bar["low"] <= current_fvg["top"])
                if not in_fvg:
                    if bar["high"] < current_fvg["bottom"] or bar["low"] > current_fvg["top"]:
                        log.event(2, "Invalid: Swept outside FVG", bar["time"],
                                  bar["close"], "M3")
                        state = "WAIT_FVG"
                        continue

                if bar["close"] < bar["open"]:
                    log.event(2, "Bearish Absorption Candle", bar["time"],
                              bar["close"], "M3",
                              f"Swept high @ {current_swing['price']:.2f}, "
                              f"closed bearish.")

                    sl = round(bar["high"] * 1.0002, 5)
                    tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                    log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"fvg_top": current_fvg["top"],
                               "fvg_bottom": current_fvg["bottom"],
                               "swing_high": current_swing["price"],
                               "setup_type": "TBV Absorption"})
                    trade_taken = True
                    break
                else:
                    log.event(2, "Invalid: Swept high but closed bullish",
                              bar["time"], bar["close"], "M3")
                    state = "WAIT_FVG"
                    continue

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
