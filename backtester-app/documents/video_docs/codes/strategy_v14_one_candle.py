"""
Strategy: The One-Candle Trading Strategy
Source: Faiz SMC ("This 'One Candle' Trading Strategy Is The Fastest Way To Become Profitable..")
Video: https://www.youtube.com/watch?v=gc_CIx_sgU8

Core Concept:
  1) Mark 8AM H1 candle high/low. Find nearest H1 swing levels.
  2) Wait for sweep of BOTH 8AM boundary + adjacent swing on M1.
  3) Enter on retest of breakout point or M1 FVG after candle closes inside.
  Set-and-forget: minimum 1:2 RR. No mid-trade SL adjustments.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "OneCandle"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "M1"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h1_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1 & 2: 8AM Candle + Adjacent Swing Levels ─────────────
    eight_high = 0.0
    eight_low = 0.0
    swing_high_above = 0.0
    swing_low_below = 0.0
    found = False

    for i in range(len(h1_bars)):
        ny = get_ny_time(h1_bars[i]["time"])
        if ny.hour == 8 and ny.minute == 0:
            eight_high = h1_bars[i]["high"]
            eight_low = h1_bars[i]["low"]

            log.event(1, "8AM Candle High/Low", h1_bars[i]["time"],
                      eight_high, "H1",
                      f"High={eight_high:.2f}, Low={eight_low:.2f}")

            left_bars = h1_bars[:i]
            if len(left_bars) >= 10:
                sw_highs = detect_swing_highs(left_bars)
                sw_lows = detect_swing_lows(left_bars)

                above = [s["price"] for s in sw_highs if s["price"] > eight_high]
                swing_high_above = min(above) if above else eight_high * 1.005

                below = [s["price"] for s in sw_lows if s["price"] < eight_low]
                swing_low_below = max(below) if below else eight_low * 0.995

                log.event(1, "Adjacent Swing Levels (H1)", h1_bars[i]["time"],
                          swing_high_above, "H1",
                          f"Above 8AM={swing_high_above:.2f}, "
                          f"Below 8AM={swing_low_below:.2f}")
                found = True
            break

    if not found:
        log.event(1, "8AM Candle Not Found", m1_bars[-1]["time"], 0, "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── State Machine on M1 ─────────────────────────────────────────
    state = "WAIT_SWEEP"
    sweep_direction = None
    sweep_extreme = 0.0
    break_point = 0.0
    trade_taken = False

    for i in range(1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])

        if ny.hour < 9 or ny.hour >= 14:
            continue
        if trade_taken:
            break

        # ── Step 3: Sweep both 8AM boundary + swing point ──────────
        if state == "WAIT_SWEEP":
            if bar["high"] > eight_high and bar["high"] > swing_high_above:
                sweep_direction = "bearish"
                sweep_extreme = bar["high"]
                state = "WAIT_RETURN"
                log.event(2, "Upward Sweep (Both Levels)", bar["time"],
                          bar["high"], "M1",
                          f"Swept 8AM high={eight_high:.2f} + swing "
                          f"high={swing_high_above:.2f}")

            elif bar["low"] < eight_low and bar["low"] < swing_low_below:
                sweep_direction = "bullish"
                sweep_extreme = bar["low"]
                state = "WAIT_RETURN"
                log.event(2, "Downward Sweep (Both Levels)", bar["time"],
                          bar["low"], "M1",
                          f"Swept 8AM low={eight_low:.2f} + swing "
                          f"low={swing_low_below:.2f}")

        # ── Step 4: Conservative entry ──────────────────────────────
        if state == "WAIT_RETURN":
            # Must close back inside 8AM boundary
            if sweep_direction == "bearish" and bar["close"] < eight_high:
                break_point = eight_high
                recent = m1_bars[max(0, i - 5):i + 1]
                fvgs = detect_fvg(recent)

                valid_retest = False
                entry_price = bar["close"]
                detail = ""

                # Check retest of breakout point or M1 FVG
                for j in range(1, 6):
                    if i + j >= len(m1_bars):
                        break
                    next_bar = m1_bars[i + j]
                    fvgs_after = detect_fvg([bar, next_bar] +
                                            m1_bars[max(0, i + j - 3):i + j])
                    for fvg in fvgs_after:
                        if fvg["direction"] == "bearish":
                            # Check if entry at FVG retest
                            if fvg["top"] >= next_bar["close"]:
                                valid_retest = True
                                entry_price = next_bar["close"]
                                detail = "M1 FVG retest"
                                break
                    if valid_retest:
                        break

                # Also accept immediate close inside as entry
                if not valid_retest:
                    valid_retest = True
                    entry_price = bar["close"]
                    detail = "close inside 8AM range"

                log.event(3, "Conservative Entry (Bearish)", bar["time"],
                          entry_price, "M1",
                          f"Entry via {detail}. "
                          f"Min RR target: 1:2")

                sl = round(sweep_extreme * 1.0002, 5)
                tp = round(eight_low, 5)
                risk = sl - entry_price
                reward = entry_price - tp
                if risk > 0 and reward / risk < 2.0:
                    tp = round(entry_price - risk * 2, 5)
                    detail += " | RR adjusted to 1:2 min"

                log.trade(
                    "SHORT", entry_price, sl, tp, bar["time"],
                    symbol, STRATEGY_NAME,
                    {"eight_high": eight_high, "eight_low": eight_low,
                     "swing_high": swing_high_above,
                     "swing_low": swing_low_below,
                     "sweep_extreme": sweep_extreme, "detail": detail}
                )
                trade_taken = True
                break

            elif sweep_direction == "bullish" and bar["close"] > eight_low:
                break_point = eight_low
                recent = m1_bars[max(0, i - 5):i + 1]
                fvgs = detect_fvg(recent)

                valid_retest = False
                entry_price = bar["close"]
                detail = ""

                for j in range(1, 6):
                    if i + j >= len(m1_bars):
                        break
                    next_bar = m1_bars[i + j]
                    fvgs_after = detect_fvg([bar, next_bar] +
                                            m1_bars[max(0, i + j - 3):i + j])
                    for fvg in fvgs_after:
                        if fvg["direction"] == "bullish":
                            if fvg["bottom"] <= next_bar["close"]:
                                valid_retest = True
                                entry_price = next_bar["close"]
                                detail = "M1 FVG retest"
                                break
                    if valid_retest:
                        break

                if not valid_retest:
                    valid_retest = True
                    entry_price = bar["close"]
                    detail = "close inside 8AM range"

                log.event(3, "Conservative Entry (Bullish)", bar["time"],
                          entry_price, "M1",
                          f"Entry via {detail}. "
                          f"Min RR target: 1:2")

                sl = round(sweep_extreme * 0.9998, 5)
                tp = round(eight_high, 5)
                risk = entry_price - sl
                reward = tp - entry_price
                if risk > 0 and reward / risk < 2.0:
                    tp = round(entry_price + risk * 2, 5)
                    detail += " | RR adjusted to 1:2 min"

                log.trade(
                    "LONG", entry_price, sl, tp, bar["time"],
                    symbol, STRATEGY_NAME,
                    {"eight_high": eight_high, "eight_low": eight_low,
                     "swing_high": swing_high_above,
                     "swing_low": swing_low_below,
                     "sweep_extreme": sweep_extreme, "detail": detail}
                )
                trade_taken = True
                break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
