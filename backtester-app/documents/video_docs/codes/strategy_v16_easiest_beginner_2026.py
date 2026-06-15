"""
Strategy: The Easiest Trading Strategy for Beginners in 2026
Source: Faiz SMC ("The Easiest Trading Strategy for Beginners in 2026")
Video: https://www.youtube.com/watch?v=VkoUIMsgDZ0

Core Concept:
  H1 8AM candle + nearest H1 PD Array (OB, FVG, swing). Must sweep both.
  M1 MSS/CISD + close inside 8AM range → enter on M1 FVG/breaker retest.
  Exactly one trade/day. Opposite 8AM boundary is TP.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "EasiestBeginner2026"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "M1"]


def find_pd_array_above(bars: list, above_price: float) -> dict | None:
    """Find nearest H1 PD Array (swing high, OB, FVG) above a price."""
    sw_highs = detect_swing_highs(bars)
    above = [s for s in sw_highs if s["price"] > above_price]
    if not above:
        return None
    nearest = min(above, key=lambda x: x["price"])
    return {"type": "swing high", "price": nearest["price"]}


def find_pd_array_below(bars: list, below_price: float) -> dict | None:
    """Find nearest H1 PD Array below a price."""
    sw_lows = detect_swing_lows(bars)
    below = [s for s in sw_lows if s["price"] < below_price]
    if not below:
        return None
    nearest = max(below, key=lambda x: x["price"])
    return {"type": "swing low", "price": nearest["price"]}


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h1_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: 8AM candle + PD Array ───────────────────────────────
    eight_high = 0.0
    eight_low = 0.0
    pd_above = None
    pd_below = None
    found = False

    for i in range(len(h1_bars)):
        ny = get_ny_time(h1_bars[i]["time"])
        if ny.hour == 8 and ny.minute == 0:
            eight_high = h1_bars[i]["high"]
            eight_low = h1_bars[i]["low"]

            log.event(1, "8AM Candle Closed", h1_bars[i]["time"],
                      eight_high, "H1",
                      f"High={eight_high:.2f}, Low={eight_low:.2f}")

            left_bars = h1_bars[:i]
            pd_above = find_pd_array_above(left_bars, eight_high)
            pd_below = find_pd_array_below(left_bars, eight_low)

            log.event(1, "PD Array Levels", h1_bars[i]["time"],
                      eight_high, "H1",
                      f"Above 8AM: {pd_above['type']} @ {pd_above['price']:.2f}" if pd_above else "None above"
                      f" | Below 8AM: {pd_below['type']} @ {pd_below['price']:.2f}" if pd_below else "None below")
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
    trade_taken = False
    current_trade_date = None

    for i in range(1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])

        if ny.hour < 9 or ny.hour >= 14:
            continue
        if trade_taken:
            break

        # Exactly one trade per day
        if current_trade_date != ny.date():
            current_trade_date = ny.date()

        # ── Step 2: Sweep both 8AM boundary + PD Array ────────────
        if state == "WAIT_SWEEP":
            pd_target = pd_above
            boundary = eight_high
            opp_boundary = eight_low

            if bar["high"] > eight_high and pd_above and bar["high"] > pd_above["price"]:
                sweep_direction = "bearish"
                sweep_extreme = bar["high"]
                state = "WAIT_CONFIRM"
                log.event(2, "Bearish Sweep: 8AM High + PD Above", bar["time"],
                          bar["high"], "M1",
                          f"Swept 8AM high={eight_high:.2f} + "
                          f"{pd_above['type']}={pd_above['price']:.2f}")

            elif bar["low"] < eight_low and pd_below and bar["low"] < pd_below["price"]:
                sweep_direction = "bullish"
                sweep_extreme = bar["low"]
                state = "WAIT_CONFIRM"
                log.event(2, "Bullish Sweep: 8AM Low + PD Below", bar["time"],
                          bar["low"], "M1",
                          f"Swept 8AM low={eight_low:.2f} + "
                          f"{pd_below['type']}={pd_below['price']:.2f}")

        # ── Confirmation: MSS/CISD + close inside 8AM range ──────
        if state == "WAIT_CONFIRM":
            if sweep_direction == "bearish":
                if not (bar["close"] < eight_high):
                    continue
                recent = m1_bars[max(0, i - 8):i + 1]
                mss = [s for s in detect_mss(recent) if s["direction"] == "bearish"]
                cisd = [s for s in detect_cisd(recent) if s["direction"] == "bearish"]
                if not (mss or cisd):
                    continue

                trigger = "MSS" if mss else "CISD"
                log.event(3, f"Bearish {trigger} + Close Inside",
                          bar["time"], bar["close"], "M1",
                          f"Close back below 8AM high={eight_high:.2f}.")

                # Find M1 FVG or breaker for optimized entry
                fvgs = detect_fvg(m1_bars[max(0, i - 5):i + 1])
                bear_fvgs = [f for f in fvgs if f["direction"] == "bearish"]
                entry = bar["close"]
                entry_detail = "close trigger"
                if bear_fvgs:
                    entry = bear_fvgs[-1]["top"]
                    entry_detail = "bearish M1 FVG retest"

                sl = round(sweep_extreme * 1.0002, 5)
                tp = round(eight_low, 5)

                log.trade("SHORT", entry, sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"eight_high": eight_high, "eight_low": eight_low,
                           "pd_above": pd_above, "pd_below": pd_below,
                           "sweep_extreme": sweep_extreme, "trigger": trigger,
                           "entry_detail": entry_detail})
                trade_taken = True
                break

            else:  # bullish
                if not (bar["close"] > eight_low):
                    continue
                recent = m1_bars[max(0, i - 8):i + 1]
                mss = [s for s in detect_mss(recent) if s["direction"] == "bullish"]
                cisd = [s for s in detect_cisd(recent) if s["direction"] == "bullish"]
                if not (mss or cisd):
                    continue

                trigger = "MSS" if mss else "CISD"
                log.event(3, f"Bullish {trigger} + Close Inside",
                          bar["time"], bar["close"], "M1",
                          f"Close back above 8AM low={eight_low:.2f}.")

                fvgs = detect_fvg(m1_bars[max(0, i - 5):i + 1])
                bull_fvgs = [f for f in fvgs if f["direction"] == "bullish"]
                entry = bar["close"]
                entry_detail = "close trigger"
                if bull_fvgs:
                    entry = bull_fvgs[-1]["bottom"]
                    entry_detail = "bullish M1 FVG retest"

                sl = round(sweep_extreme * 0.9998, 5)
                tp = round(eight_high, 5)

                log.trade("LONG", entry, sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"eight_high": eight_high, "eight_low": eight_low,
                           "pd_above": pd_above, "pd_below": pd_below,
                           "sweep_extreme": sweep_extreme, "trigger": trigger,
                           "entry_detail": entry_detail})
                trade_taken = True
                break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
