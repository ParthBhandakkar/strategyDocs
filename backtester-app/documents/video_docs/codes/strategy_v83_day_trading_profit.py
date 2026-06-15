"""
Strategy: Day Trading for Profit (NQ 2M iFVG)
Source: Faiz SMC ("How I Made $2,600 In 10 Minutes Day Trading")
Video: https://www.youtube.com/watch?v=FtDqcK4TUME

Core Concept:
  Build "story" on D1/H1 (external vs internal liquidity, volume
  imbalance). 2M execution after 9:30 AM NY. Identify fake MSS
  before 9:30, true sweep after. FVG inversion entry.
  1:2-1:3 target. Only trade after 9:30 AM open.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "DayTradingProfit"
SYMBOL = "NQ"
TIMEFRAMES = ["D1", "H1", "M2"]


def build_story(daily_bars: list, h1_bars: list):
    """Build directional story from D1/H1 context."""
    story = {}

    if daily_bars and len(daily_bars) >= 3:
        recent_high = max(b["high"] for b in daily_bars[-3:])
        recent_low = min(b["low"] for b in daily_bars[-3:])
        story["daily_range"] = (recent_low, recent_high)

    if h1_bars and len(h1_bars) >= 4:
        recent_highs = [b["high"] for b in h1_bars[-4:]]
        recent_lows = [b["low"] for b in h1_bars[-4:]]
        story["direction"] = "bullish" if h1_bars[-1]["close"] > h1_bars[-2]["close"] else "bearish"
        story["eq_highs"] = max(recent_highs)
        story["eq_lows"] = min(recent_lows)

    return story


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    daily_bars = get_bars(data_dir, symbol, "D1")
    h1_bars = get_bars(data_dir, symbol, "H1")
    m2_bars = get_bars(data_dir, symbol, "M2")

    if not m2_bars:
        print("No data found")
        return

    # ── Step 1: Build story ─────────────────────────────────────────
    story = build_story(daily_bars, h1_bars)

    if "direction" in story:
        log.event(1, f"Story: {story['direction'].upper()}, "
                  f"Daily Range: {story.get('daily_range', 'N/A')}",
                  m2_bars[-1]["time"], 0, "D1/H1")

    # ── Step 2-3: 2M after 9:30 AM ──────────────────────────────────
    for i in range(3, len(m2_bars)):
        ny = get_ny_time(m2_bars[i]["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11 and ny.minute > 30:
            break

        bar = m2_bars[i]

        # ── True sweep after 9:30 ───────────────────────────────
        lookback = max(0, i - 10)
        recent_high = max(b["high"] for b in m2_bars[lookback:i])
        recent_low = min(b["low"] for b in m2_bars[lookback:i])

        direction = story.get("direction", "bullish")
        swept = False

        if direction == "bullish" and bar["low"] < recent_low:
            swept = True
            log.event(2, "True Sweep (Low) after 9:30AM",
                      bar["time"], bar["low"], "M2")
        elif direction == "bearish" and bar["high"] > recent_high:
            swept = True
            log.event(2, "True Sweep (High) after 9:30AM",
                      bar["time"], bar["high"], "M2")

        if not swept:
            continue

        # ── FVG inversion entry ────────────────────────────────
        fvgs = detect_fvg(
            m2_bars[max(0, i - 6):i + 1]
        )

        if not fvgs:
            continue

        for fvg in fvgs:
            if direction == "bullish" and bar["close"] > fvg["top"]:
                log.event(3, "FVG Inversion (Long)", bar["time"],
                          bar["close"], "M2",
                          f"FVG: {fvg['top']:.2f}-{fvg['bottom']:.2f}")

                sl = round(bar["low"] * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2.5, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"story_direction": direction,
                           "management": "1:2-1:3 target"})
                break

            if direction == "bearish" and bar["close"] < fvg["bottom"]:
                log.event(3, "FVG Inversion (Short)", bar["time"],
                          bar["close"], "M2",
                          f"FVG: {fvg['top']:.2f}-{fvg['bottom']:.2f}")

                sl = round(bar["high"] * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2.5, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"story_direction": direction,
                           "management": "1:2-1:3 target"})
                break
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
