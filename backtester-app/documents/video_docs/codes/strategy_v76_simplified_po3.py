"""
Strategy: Simplified ICT PO3 (Power of 3) Trading Strategy
Source: Faiz SMC ("I Simplified ICT PO3 Trading Strategy...")
Video: https://www.youtube.com/watch?v=HT49YvYH9NQ

Core Concept:
  Daily bias from last 2 candles: d2 close > d1 high = bullish,
  d2 wick > d1 high + close below = bearish.
  15M manipulation: wick that sweeps significant liquidity opposite
  expected direction. Fib -2 to -2.5 extension marks valid manipulation.
  Entry on MSS + FVG. 1:2-1:3 target.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "SimplifiedPO3"
SYMBOL = "NQ"
TIMEFRAMES = ["D1", "M15", "M5"]


def determine_daily_bias(daily_bars: list):
    """Determine daily bias from last 2 daily candles."""
    if len(daily_bars) < 3:
        return None, None

    d1 = daily_bars[-3]
    d2 = daily_bars[-2]
    d3 = daily_bars[-1]

    d3_open = d3["open"]

    if d2["close"] > d1["high"]:
        return "bullish", d3_open

    # d2 wicks above d1 high but closes below = bearish
    if d2["high"] > d1["high"] and d2["close"] < d1["high"]:
        return "bearish", d3_open

    return None, d3_open


def find_manipulation_swing(m15_bars: list, d3_open: float, direction: str):
    """
    Find a 15M manipulation move that sweeps liquidity opposite to bias.
    For bullish bias: look for wick that sweeps low (discount).
    For bearish bias: look for wick that sweeps high (premium).
    """
    if len(m15_bars) < 5:
        return None, None

    # Look for bars that wick opposite to bias
    if direction == "bullish":
        for i in range(1, len(m15_bars)):
            if m15_bars[i]["low"] < m15_bars[i - 1]["low"]:
                # Check if it swept a significant low
                lookback = max(0, i - 10)
                recent_lows = [b["low"] for b in m15_bars[lookback:i]]
                if recent_lows and m15_bars[i]["low"] < min(recent_lows):
                    return m15_bars[i]["low"], i
    else:
        for i in range(1, len(m15_bars)):
            if m15_bars[i]["high"] > m15_bars[i - 1]["high"]:
                lookback = max(0, i - 10)
                recent_highs = [b["high"] for b in m15_bars[lookback:i]]
                if recent_highs and m15_bars[i]["high"] > max(recent_highs):
                    return m15_bars[i]["high"], i

    return None, None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    daily_bars = get_bars(data_dir, symbol, "D1")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m5_bars = get_bars(data_dir, symbol, "M5")

    if not daily_bars or not m15_bars:
        print("No data found")
        return

    # ── Step 1: Daily bias ──────────────────────────────────────────
    bias, d3_open = determine_daily_bias(daily_bars)
    if bias is None:
        log.event(1, "No clear daily bias", daily_bars[-1]["time"],
                  daily_bars[-1]["close"], "D1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"Daily Bias: {bias.upper()}, D3 Open={d3_open:.2f}",
              daily_bars[-1]["time"], d3_open, "D1")

    # ── Step 2: Find manipulation ───────────────────────────────────
    manip_level, manip_idx = find_manipulation_swing(
        m15_bars, d3_open, bias
    )

    if manip_level is None:
        log.event(2, "No manipulation sweep found", m15_bars[-1]["time"],
                  0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(2, f"Manipulation Sweep ({bias.upper()})",
              m15_bars[manip_idx]["time"],
              manip_level, "M15",
              f"Level: {manip_level:.2f}")

    # ── Step 3: MSS + FVG entry ─────────────────────────────────────
    for i in range(manip_idx + 1, len(m15_bars)):
        bar = m15_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 8 or ny.hour > 16:
            continue

        seg = m15_bars[max(0, i - 6):i + 1]
        if len(seg) < 3:
            continue

        # MSS check
        recent_high = max(b["high"] for b in seg[:-1])
        recent_low = min(b["low"] for b in seg[:-1])

        mss_ok = False
        if bias == "bullish":
            if bar["close"] > bar["open"] and bar["close"] > recent_high:
                mss_ok = True
        else:
            if bar["close"] < bar["open"] and bar["close"] < recent_low:
                mss_ok = True

        if not mss_ok:
            continue

        # Check for FVG in the move
        fvgs = detect_fvg(seg)
        has_fvg = any(
            (bias == "bullish" and f["direction"] == "bullish") or
            (bias == "bearish" and f["direction"] == "bearish")
            for f in fvgs
        )

        log.event(3, f"MSS + {'FVG' if has_fvg else 'Structure Shift'} "
                  f"({bias.upper()})",
                  bar["time"], bar["close"], "M15")

        if bias == "bullish":
            sl = round(bar["low"] * 0.9998, 5)
            tp = round(bar["close"] + (bar["close"] - sl) * 2.5, 5)
            log.trade("LONG", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"bias": "bullish", "d3_open": d3_open,
                       "manipulation_level": manip_level,
                       "management": "1:2-1:3 RR"})
        else:
            sl = round(bar["high"] * 1.0002, 5)
            tp = round(bar["close"] - (sl - bar["close"]) * 2.5, 5)
            log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"bias": "bearish", "d3_open": d3_open,
                       "manipulation_level": manip_level,
                       "management": "1:2-1:3 RR"})
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
