"""
Strategy: Easy ICT Trading Strategy for 2025 (PO3 Daily/Weekly)
Source: Faiz SMC ("Use This Easy ICT Trading Strategy In 2025 To Quit Your Job In 60 Days!")
Video: https://www.youtube.com/watch?v=08Tv4nOccCg

Core Concept:
  Daily (or Weekly) bias from last 2 candles: d2 close > d1 high =
  bullish; d2 close < d1 low = bearish; otherwise flipped.
  D3 open is reference. 15M (daily) or 1H (weekly) manipulation sweep
  of liquidity to left of open. Fib -2 to -2.5 extension validation.
  MSS + OB/FVG entry. 1:2 target. Best on Futures.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "EasyICT2025PO3"
SYMBOL = "NQ"
TIMEFRAMES = ["D1", "M15", "M5"]


def determine_bias(daily_bars: list):
    """Determine daily bias from last 2 candles."""
    if len(daily_bars) < 3:
        return None, None

    d1 = daily_bars[-3]
    d2 = daily_bars[-2]
    d3_open = daily_bars[-1]["open"]

    if d2["close"] > d1["high"]:
        return "bullish", d3_open
    if d2["close"] < d1["low"]:
        return "bearish", d3_open

    # Flipped bias: if d2 fails to close above/below
    if d2["close"] < d1["close"]:
        return "bearish", d3_open
    return "bullish", d3_open


def find_manipulation(bars: list, d3_open: float, direction: str):
    """Find manipulation sweep on 15M."""
    for i in range(1, len(bars)):
        if direction == "bullish":
            lookback = max(0, i - 8)
            recent_lows = [b["low"] for b in bars[lookback:i]]
            if recent_lows and bars[i]["low"] < min(recent_lows):
                return bars[i]["low"], i
        else:
            lookback = max(0, i - 8)
            recent_highs = [b["high"] for b in bars[lookback:i]]
            if recent_highs and bars[i]["high"] > max(recent_highs):
                return bars[i]["high"], i
    return None, None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    daily_bars = get_bars(data_dir, symbol, "D1")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m5_bars = get_bars(data_dir, symbol, "M5")

    if not daily_bars or not m15_bars:
        print("No data found")
        return

    # ── Step 1: Bias ────────────────────────────────────────────────
    bias, d3_open = determine_bias(daily_bars)
    if bias is None:
        log.event(1, "Could not determine bias", daily_bars[-1]["time"],
                  daily_bars[-1]["close"], "D1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"Daily Bias: {bias.upper()}, D3 Open={d3_open:.2f}",
              daily_bars[-1]["time"], d3_open, "D1")

    # ── Step 2: Find manipulation on 15M ────────────────────────────
    manip_level, manip_idx = find_manipulation(m15_bars, d3_open, bias)

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

    # ── Step 2.5: Fib validation (-2 extension) ─────────────────────
    # (simplified: check if manip level is beyond recent range)
    before_manip = m15_bars[max(0, manip_idx - 8):manip_idx + 1]
    if before_manip:
        if bias == "bullish":
            range_size = max(b["high"] for b in before_manip) - \
                         min(b["low"] for b in before_manip)
            manip_range = abs(manip_level - min(b["low"] for b in before_manip))
            fib_ext = manip_range / range_size if range_size > 0 else 0
            log.event(3, f"Fib Extension: {fib_ext:.2f}x (target -2 to -2.5)",
                      m15_bars[manip_idx]["time"], manip_level, "M15")

    # ── Step 3: MSS + OB/FVG entry ──────────────────────────────────
    for i in range(manip_idx + 1, len(m15_bars)):
        bar = m15_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 8 or ny.hour > 16:
            continue

        seg = m15_bars[max(0, i - 6):i + 1]
        if len(seg) < 3:
            continue

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

        log.event(4, f"MSS + Entry ({bias.upper()})", bar["time"],
                  bar["close"], "M15")

        if bias == "bullish":
            sl = round(bar["low"] * 0.9998, 5)
            tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
            log.trade("LONG", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"bias": "bullish", "d3_open": d3_open,
                       "manip_level": manip_level,
                       "management": "BE at 1:1, 1:2 target"})
        else:
            sl = round(bar["high"] * 1.0002, 5)
            tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
            log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"bias": "bearish", "d3_open": d3_open,
                       "manip_level": manip_level,
                       "management": "BE at 1:1, 1:2 target"})
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
