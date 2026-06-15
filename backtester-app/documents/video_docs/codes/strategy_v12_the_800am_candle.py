"""
Strategy: The 8:00 AM Candle Strategy
Source: Faiz SMC ("This 8AM Candle Strategy Is Boring, But It Makes F*ck You Money")
Video: https://www.youtube.com/watch?v=2cuaTYjEw9Q

Core Concept:
  1) Wait for 8AM NY H1 candle to close at 9AM → mark high/low.
  2) Find nearest H1 swing high above 8AM high, H1 swing low below 8AM low.
  3) Price must sweep BOTH the 8AM boundary AND the adjacent swing point.
  4) On M1: wait for MSS or IFVG + close back inside 8AM boundary.
  5) Enter, SL past sweep extreme, TP at 50% midpoint (partial) and opposite boundary.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "EightAMCandle"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "M1"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h1_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1, 2, 3: Find 8AM candle and adjacent swing levels ──────
    eight_high = 0.0
    eight_low = 0.0
    eight_mid = 0.0
    swing_high_above = 0.0
    swing_low_below = 0.0
    found = False

    for i in range(len(h1_bars)):
        ny = get_ny_time(h1_bars[i]["time"])
        if ny.hour == 8 and ny.minute == 0:
            eight_high = h1_bars[i]["high"]
            eight_low = h1_bars[i]["low"]
            eight_mid = fib_retracement(eight_high, eight_low, 0.5)

            log.event(
                1, "8AM Candle Closed", h1_bars[i]["time"], eight_high, "H1",
                f"High={eight_high:.2f}, Low={eight_low:.2f}, "
                f"Midpoint={eight_mid:.2f}"
            )

            # Find adjacent swing levels
            left_bars = h1_bars[:i]
            if len(left_bars) >= 10:
                sw_highs = detect_swing_highs(left_bars)
                sw_lows = detect_swing_lows(left_bars)

                # Nearest swing high above 8AM high
                above = [s["price"] for s in sw_highs if s["price"] > eight_high]
                swing_high_above = min(above) if above else eight_high * 1.005

                # Nearest swing low below 8AM low
                below = [s["price"] for s in sw_lows if s["price"] < eight_low]
                swing_low_below = max(below) if below else eight_low * 0.995

                log.event(
                    1, "Adjacent Swing Levels Identified", h1_bars[i]["time"],
                    swing_high_above, "H1",
                    f"Swing High Above 8AM={swing_high_above:.2f}, "
                    f"Swing Low Below 8AM={swing_low_below:.2f}"
                )
                found = True
            break

    if not found:
        log.event(1, "8AM Candle Not Found", m1_bars[-1]["time"], 0, "H1",
                  "No candle with hour=8 found in data.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── State Machine on M1 ─────────────────────────────────────────
    state = "WAIT_SWEEP"
    sweep_direction = None
    sweep_price = 0.0
    trade_taken = False

    for i in range(1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])

        # Only trade between 9:00 AM and 2:00 PM
        if ny.hour < 9:
            continue
        if ny.hour >= 14:
            break

        if trade_taken:
            break

        # ── Step 4: Wait for sweep of BOTH 8AM boundary AND swing point ─
        if state == "WAIT_SWEEP":
            # Check for upward sweep (short setup)
            if bar["high"] > eight_high and bar["high"] > swing_high_above:
                sweep_direction = "bearish"
                sweep_price = bar["high"]
                state = "WAIT_REVERSAL_SHORT"
                log.event(
                    2, "Upward Sweep Detected", bar["time"], bar["high"], "M1",
                    f"Both 8AM high ({eight_high:.2f}) and swing high "
                    f"({swing_high_above:.2f}) swept. Looking for MSS/IFVG."
                )

            # Check for downward sweep (long setup)
            elif bar["low"] < eight_low and bar["low"] < swing_low_below:
                sweep_direction = "bullish"
                sweep_price = bar["low"]
                state = "WAIT_REVERSAL_LONG"
                log.event(
                    2, "Downward Sweep Detected", bar["time"], bar["low"], "M1",
                    f"Both 8AM low ({eight_low:.2f}) and swing low "
                    f"({swing_low_below:.2f}) swept. Looking for MSS/IFVG."
                )

        # ── Step 5: Entry Validation (MSS or IFVG + close back inside) ─
        if state == "WAIT_REVERSAL_SHORT":
            # Must close back inside 8AM boundary (below 8AM high)
            if bar["close"] < eight_high:
                recent = m1_bars[max(0, i - 6):i + 1]
                mss = detect_mss(recent)
                ifvg = detect_ifvg(recent)

                bearish_mss = [s for s in mss if s["direction"] == "bearish"]
                bearish_ifvg = [s for s in ifvg if s["direction"] == "bearish"]

                if bearish_mss or bearish_ifvg:
                    trigger = "MSS" if bearish_mss else "IFVG"
                    log.event(
                        3, f"Bearish {trigger} + Close Inside 8AM Range",
                        bar["time"], bar["close"], "M1",
                        f"Price closed back below 8AM high ({eight_high:.2f}). "
                        f"Short trigger confirmed."
                    )

                    sl = round(sweep_price * 1.0002, 5)
                    tp = round(eight_mid, 5)

                    log.trade(
                        "SHORT", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                        {"eight_high": eight_high, "eight_low": eight_low,
                         "eight_mid": eight_mid, "swing_high": swing_high_above,
                         "swing_low": swing_low_below, "sweep_price": sweep_price,
                         "trigger": trigger,
                         "tp_final": eight_low}
                    )
                    trade_taken = True
                    break

        if state == "WAIT_REVERSAL_LONG":
            if bar["close"] > eight_low:
                recent = m1_bars[max(0, i - 6):i + 1]
                mss = detect_mss(recent)
                ifvg = detect_ifvg(recent)

                bullish_mss = [s for s in mss if s["direction"] == "bullish"]
                bullish_ifvg = [s for s in ifvg if s["direction"] == "bullish"]

                if bullish_mss or bullish_ifvg:
                    trigger = "MSS" if bullish_mss else "IFVG"
                    log.event(
                        3, f"Bullish {trigger} + Close Inside 8AM Range",
                        bar["time"], bar["close"], "M1",
                        f"Price closed back above 8AM low ({eight_low:.2f}). "
                        f"Long trigger confirmed."
                    )

                    sl = round(sweep_price * 0.9998, 5)
                    tp = round(eight_mid, 5)

                    log.trade(
                        "LONG", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                        {"eight_high": eight_high, "eight_low": eight_low,
                         "eight_mid": eight_mid, "swing_high": swing_high_above,
                         "swing_low": swing_low_below, "sweep_price": sweep_price,
                         "trigger": trigger,
                         "tp_final": eight_high}
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
