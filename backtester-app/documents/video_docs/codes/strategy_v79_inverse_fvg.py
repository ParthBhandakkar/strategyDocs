"""
Strategy: SMC Doesn't Work — Use Inverse FVG Instead
Source: Faiz SMC ("SMC Doesn't Work Anymore..? Use This Instead!")
Video: https://www.youtube.com/watch?v=HqmhaQrVxMM

Core Concept:
  4H only. Identify order flow (trend). Mark dealing range (recent
  low to recent high). Sweep of liquidity opposite trend direction.
  Entry: inverse FVG in dealing range. Single FVG → inverse and enter.
  Multiple FVGs → wait for extreme FVG to be inversed first.
  No MSS required. BE at closest liquidity sweep. 35-40% partial at
  1:1, full exit at 2-2.5x RR.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "InverseFVG"
SYMBOL = "USDCHF"
TIMEFRAMES = ["H4", "H1"]


def detect_orderflow(bars_h4: list):
    if len(bars_h4) < 6:
        return None
    recent = bars_h4[-6:]
    highs = [b["high"] for b in recent]
    lows = [b["low"] for b in recent]
    if highs[-1] > highs[-2] > highs[-3] and lows[-1] > lows[-2]:
        return "bullish"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2] < lows[-3]:
        return "bearish"
    return None


def find_dealing_range(bars_h4: list):
    """Find the dealing range (recent low to recent high)."""
    recent = bars_h4[-6:]
    range_low = min(b["low"] for b in recent)
    range_high = max(b["high"] for b in recent)
    return range_high, range_low


def find_fvgs_in_range(bars_h4: list, range_low: float, range_high: float):
    """Find all FVGs within the dealing range."""
    fvgs = detect_fvg(bars_h4)
    return [
        f for f in fvgs
        if f["bottom"] >= range_low and f["top"] <= range_high
    ]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "H4")
    h1_bars = get_bars(data_dir, symbol, "H1")

    if not h4_bars:
        print("No data found")
        return

    # ── Step 1: Order flow ──────────────────────────────────────────
    direction = detect_orderflow(h4_bars)
    if direction is None:
        log.event(1, "No clear 4H order flow", h4_bars[-1]["time"],
                  h4_bars[-1]["close"], "H4")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"4H Order Flow: {direction.upper()}", h4_bars[-1]["time"],
              h4_bars[-1]["close"], "H4")

    # ── Step 2: Dealing range + FVGs ────────────────────────────────
    range_high, range_low = find_dealing_range(h4_bars)

    log.event(2, "Dealing Range", h4_bars[-1]["time"], range_high, "H4",
              f"High={range_high:.5f}, Low={range_low:.5f}")

    fvgs = find_fvgs_in_range(h4_bars, range_low, range_high)

    if not fvgs:
        log.event(3, "No FVGs in dealing range", h4_bars[-1]["time"],
                  0, "H4")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(3, f"FVGs in Dealing Range: {len(fvgs)}",
              h4_bars[-1]["time"], 0, "H4")

    # ── Step 3: Wait for sweep + FVG inversion ──────────────────────
    swept = False
    target_fvg = None

    for i in range(0, len(h4_bars)):
        bar = h4_bars[i]
        ny = get_ny_time(bar["time"])

        # Sweep in opposite direction of trend
        if not swept:
            if direction == "bullish" and bar["low"] < range_low:
                log.event(4, "Liquidity Swept (Low)", bar["time"],
                          bar["low"], "H4")
                swept = True
                sweep_side = "low"
                sweep_idx = i
            elif direction == "bearish" and bar["high"] > range_high:
                log.event(4, "Liquidity Swept (High)", bar["time"],
                          bar["high"], "H4")
                swept = True
                sweep_side = "high"
                sweep_idx = i
            continue

        # After sweep: check for FVG inversion
        if sweep_side is None:
            continue

        # Determine target FVG for inversion
        if target_fvg is None:
            if direction == "bullish":
                # Find most extreme (lowest bullish) FVG
                bullish_fvgs = [f for f in fvgs if f["direction"] == "bullish"]
                if not bullish_fvgs:
                    continue
                target_fvg = min(bullish_fvgs, key=lambda f: f["bottom"])
            else:
                bearish_fvgs = [f for f in fvgs if f["direction"] == "bearish"]
                if not bearish_fvgs:
                    continue
                target_fvg = max(bearish_fvgs, key=lambda f: f["top"])

        # Check inversion
        inversed = False
        if direction == "bullish" and bar["close"] > target_fvg["top"]:
            inversed = True
            log.event(5, "FVG Inversed (Long Entry)", bar["time"],
                      bar["close"], "H4",
                      f"FVG: {target_fvg['top']:.5f}-{target_fvg['bottom']:.5f}")
        elif direction == "bearish" and bar["close"] < target_fvg["bottom"]:
            inversed = True
            log.event(5, "FVG Inversed (Short Entry)", bar["time"],
                      bar["close"], "H4",
                      f"FVG: {target_fvg['top']:.5f}-{target_fvg['bottom']:.5f}")

        if not inversed:
            continue

        if direction == "bullish":
            sl = round(bar["low"] * 0.9998, 5)
            tp = round(bar["close"] + (bar["close"] - sl) * 2.25, 5)
            log.trade("LONG", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"4h_trend": "bullish",
                       "dealing_range": f"{range_low:.5f}-{range_high:.5f}",
                       "fvg_inversed": f"{target_fvg['top']:.5f}-{target_fvg['bottom']:.5f}",
                       "management": "35-40% partial at 1:1, "
                                     "full exit at 2-2.5x, BE at closest sweep"})
        else:
            sl = round(bar["high"] * 1.0002, 5)
            tp = round(bar["close"] - (sl - bar["close"]) * 2.25, 5)
            log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"4h_trend": "bearish",
                       "dealing_range": f"{range_low:.5f}-{range_high:.5f}",
                       "fvg_inversed": f"{target_fvg['top']:.5f}-{target_fvg['bottom']:.5f}",
                       "management": "35-40% partial at 1:1, "
                                     "full exit at 2-2.5x, BE at closest sweep"})
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
