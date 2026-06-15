"""
Strategy: Liquidity Range Trading Strategy
Source: Faiz SMC ("The Only Liquidity Strategy You'll Ever Need")
Video: http://www.youtube.com/watch?v=LivWGyobZcA

Core Concept:
  5M timeframe. Identify trend push → pullback → MSS defines range high
  and low. Wait for sweep of range extreme. Confirm with 5M market
  structure shift + price closure back inside range.
  Enter via auto block or breaker block. 3 trades max per day.
  BE at 1:1.5, partial at 1:2 (30-35%), mid-range partial, final TP
  at opposite range extreme.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "LiquidityRange"
SYMBOL = "NQ"
TIMEFRAMES = ["M5"]


def find_range_structure(bars: list, idx: int, lookback: int = 24):
    """
    Find a range defined by a push and a pullback MSS.
    Returns (range_high, range_low, direction) or None.
    """
    seg = bars[max(0, idx - lookback):idx + 1]
    if len(seg) < 6:
        return None

    highs = []
    lows = []
    for j in range(1, len(seg) - 1):
        if seg[j]["high"] > seg[j - 1]["high"] and seg[j]["high"] > seg[j + 1]["high"]:
            highs.append((j, seg[j]["high"]))
        if seg[j]["low"] < seg[j - 1]["low"] and seg[j]["low"] < seg[j + 1]["low"]:
            lows.append((j, seg[j]["low"]))

    if len(highs) < 1 or len(lows) < 1:
        return None

    last_h = max(highs, key=lambda x: x[0])
    last_l = max(lows, key=lambda x: x[0])

    # Bullish range: push up (high formed after low) → pullback MSS
    if last_h[0] > last_l[0]:
        r_high = last_h[1]
        # Find MSS low in the pullback after the high
        for j in range(last_h[0], len(seg)):
            if seg[j]["low"] < last_l[1]:
                return (r_high, seg[j]["low"], "bullish")
        return (r_high, last_l[1], "bullish")

    # Bearish range
    if last_l[0] > last_h[0]:
        r_low = last_l[1]
        for j in range(last_l[0], len(seg)):
            if seg[j]["high"] > last_h[1]:
                return (seg[j]["high"], r_low, "bearish")
        return (last_h[1], r_low, "bearish")

    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m5_bars = get_bars(data_dir, symbol, "M5")
    if not m5_bars:
        print("No data found")
        return

    trades_taken = 0
    max_trades = 3
    state = "FIND_RANGE"
    range_high = 0.0
    range_low = 0.0
    range_dir = ""

    for i in range(20, len(m5_bars)):
        bar = m5_bars[i]
        if trades_taken >= max_trades:
            break

        # ── State: FIND_RANGE ───────────────────────────────────────
        if state == "FIND_RANGE":
            structure = find_range_structure(m5_bars, i)
            if structure is None:
                continue

            range_high, range_low, range_dir = structure
            state = "WAIT_SWEEP"

            log.event(1, f"Range Defined ({range_dir.upper()})", bar["time"],
                      range_high, "M5",
                      f"Range: {range_high:.2f} - {range_low:.2f}")

        # ── State: WAIT_SWEEP ───────────────────────────────────────
        elif state == "WAIT_SWEEP":
            if range_dir == "bullish":
                if bar["low"] < range_low:
                    state = "WAIT_RETURN"
                    log.event(2, "Range Low Swept", bar["time"],
                              bar["low"], "M5")
            else:
                if bar["high"] > range_high:
                    state = "WAIT_RETURN"
                    log.event(2, "Range High Swept", bar["time"],
                              bar["high"], "M5")

        # ── State: WAIT_RETURN ──────────────────────────────────────
        elif state == "WAIT_RETURN":
            # Check market structure shift + close back inside range
            if range_dir == "bullish":
                if bar["close"] > range_low and bar["close"] > bar["open"]:
                    log.event(3, "MSS + Close Inside Range (Bullish)",
                              bar["time"], bar["close"], "M5")

                    entry = bar["close"]
                    sl = round(range_low * 0.9998, 5)
                    mid_range = round((range_high + range_low) / 2, 5)
                    tp = round(range_high, 5)

                    log.trade("LONG", entry, sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"range_high": range_high,
                               "range_low": range_low,
                               "mid_range": mid_range,
                               "trade_num": trades_taken + 1,
                               "max_trades": max_trades,
                               "management": "BE at 1:1.5, partial at 1:2 (30-35%), "
                                             "mid-range partial, TP at range high"})
                    trades_taken += 1
                    state = "FIND_RANGE"
            else:
                if bar["close"] < range_high and bar["close"] < bar["open"]:
                    log.event(3, "MSS + Close Inside Range (Bearish)",
                              bar["time"], bar["close"], "M5")

                    entry = bar["close"]
                    sl = round(range_high * 1.0002, 5)
                    mid_range = round((range_high + range_low) / 2, 5)
                    tp = round(range_low, 5)

                    log.trade("SHORT", entry, sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"range_high": range_high,
                               "range_low": range_low,
                               "mid_range": mid_range,
                               "trade_num": trades_taken + 1,
                               "max_trades": max_trades,
                               "management": "BE at 1:1.5, partial at 1:2 (30-35%), "
                                             "mid-range partial, TP at range low"})
                    trades_taken += 1
                    state = "FIND_RANGE"

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
