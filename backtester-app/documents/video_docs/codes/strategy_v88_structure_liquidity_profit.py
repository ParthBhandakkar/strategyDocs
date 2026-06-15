"""
Strategy: Structure + Liquidity = Easy Profit
Source: Faiz SMC ("Structure + Liquidity = Easy Profit")
Video: https://www.youtube.com/watch?v=9NF26IyivVY

Core Concept:
  4H for structure (trend). Trade only with trend. External liquidity
  (H/L) and internal liquidity (FVG in discount/premium). 15M for MSS
  and entry. 1M for refinement. SMT divergence for confirmation.
  Entry after price enters discount/premium zone via FVG.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "StructureLiquidityProfit"
SYMBOL = "EURAUD"
TIMEFRAMES = ["H4", "M15", "M1"]


def detect_h4_structure(bars_h4: list):
    """Detect 4H trend structure."""
    if len(bars_h4) < 8:
        return None

    recent = bars_h4[-8:]
    highs = [b["high"] for b in recent]
    lows = [b["low"] for b in recent]

    if highs[-1] > highs[-2] > highs[-3] and lows[-1] > lows[-2] > lows[-3]:
        return "bullish"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2] < lows[-3]:
        return "bearish"

    return None


def find_discount_fvg(bars: list, direction: str):
    """
    Find FVG in discount/premium zone aligned with trend.
    Discount = below midpoint for bullish, premium = above for bearish.
    """
    fvgs = detect_fvg(bars)

    if not fvgs:
        return None

    range_high = max(b["high"] for b in bars[-10:])
    range_low = min(b["low"] for b in bars[-10:])
    midpoint = (range_high + range_low) / 2

    for fvg in fvgs:
        if direction == "bullish" and fvg["top"] <= midpoint and fvg["direction"] == "bullish":
            return fvg
        if direction == "bearish" and fvg["bottom"] >= midpoint and fvg["direction"] == "bearish":
            return fvg

    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "H4")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h4_bars or not m15_bars:
        print("No data found")
        return

    # ── Step 1: 4H structure ────────────────────────────────────────
    direction = detect_h4_structure(h4_bars)
    if direction is None:
        log.event(1, "No clear 4H trend structure", h4_bars[-1]["time"],
                  h4_bars[-1]["close"], "H4")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"4H Structure: {direction.upper()} (trade with trend)",
              h4_bars[-1]["time"], h4_bars[-1]["close"], "H4")

    # ── Step 2: Internal liquidity (FVG in discount/premium) ───────
    target_fvg = find_discount_fvg(m15_bars, direction)
    if target_fvg is None:
        log.event(2, "No FVG in discount/premium zone on 15M",
                  m15_bars[-1]["time"], 0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(2, f"Internal Liquidity (15M FVG in "
              f"{'discount' if direction == 'bullish' else 'premium'})",
              m15_bars[-1]["time"], target_fvg["top"], "M15",
              f"FVG: {target_fvg['top']:.5f}-{target_fvg['bottom']:.5f}")

    # ── Step 3: 15M MSS + entry ────────────────────────────────────
    for i in range(3, len(m15_bars)):
        bar = m15_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 8 or ny.hour > 16:
            continue

        # Check if price entered the FVG zone
        if bar["low"] > target_fvg["top"] or bar["high"] < target_fvg["bottom"]:
            continue

        # MSS in trend direction
        seg = m15_bars[max(0, i - 5):i + 1]
        recent_high = max(b["high"] for b in seg[:-1])
        recent_low = min(b["low"] for b in seg[:-1])

        mss_ok = False
        if direction == "bullish":
            if bar["close"] > bar["open"] and bar["close"] > recent_high:
                mss_ok = True
        else:
            if bar["close"] < bar["open"] and bar["close"] < recent_low:
                mss_ok = True

        if not mss_ok:
            continue

        log.event(3, f"15M MSS ({direction.upper()})", bar["time"],
                  bar["close"], "M15", "Entry signal")

        if direction == "bullish":
            sl = round(bar["low"] * 0.9998, 5)
            tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
            log.trade("LONG", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"4h_structure": "bullish",
                       "fvg_zone": f"{target_fvg['bottom']:.5f}-{target_fvg['top']:.5f}",
                       "management": "SL beyond structure"})
        else:
            sl = round(bar["high"] * 1.0002, 5)
            tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
            log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"4h_structure": "bearish",
                       "fvg_zone": f"{target_fvg['bottom']:.5f}-{target_fvg['top']:.5f}",
                       "management": "SL beyond structure"})
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
