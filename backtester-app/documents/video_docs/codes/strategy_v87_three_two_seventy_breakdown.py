"""
Strategy: How I Made $3,270 In 5 Minutes (1H Purge + 1M iFVG)
Source: Faiz SMC ("How I Made $3,270 In 5 Minutes Trading ICT Concepts (FULL BREAKDOWN)")
Video: https://www.youtube.com/watch?v=9hXQV9_yfOI

Core Concept:
  Discretionary: 1H liquidity purge (sweep of HTF level). Wait for
  price to hit HTF liquidity and react. 1M iFVG reversal entry.
  Experience-based reading of market flow rather than rigid rules.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "ThreeTwoSeventyBreakdown"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "M1"]


def find_h1_liquidity_levels(h1_bars: list):
    """Find recent H1 buy-side and sell-side liquidity levels."""
    if len(h1_bars) < 8:
        return None, None

    recent = h1_bars[-8:]
    buy_side = max(b["high"] for b in recent)
    sell_side = min(b["low"] for b in recent)
    return buy_side, sell_side


def check_h1_purge(h1_bars: list, buy_side: float, sell_side: float):
    """Check if H1 has purged (swept) a liquidity level."""
    if len(h1_bars) < 2:
        return None

    bar = h1_bars[-1]
    if bar["high"] > buy_side:
        return "bearish"
    if bar["low"] < sell_side:
        return "bullish"
    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h1_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: H1 analysis ─────────────────────────────────────────
    buy_side, sell_side = find_h1_liquidity_levels(h1_bars)
    if buy_side is None:
        log.event(1, "No H1 liquidity levels identified",
                  h1_bars[-1]["time"], 0, "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, "H1 Liquidity Levels", h1_bars[-1]["time"],
              buy_side, "H1",
              f"Buy-side={buy_side:.2f}, Sell-side={sell_side:.2f}")

    # ── Step 2: Check for purge ─────────────────────────────────────
    purge_dir = check_h1_purge(h1_bars, buy_side, sell_side)
    if purge_dir is None:
        log.event(2, "No H1 liquidity purge", h1_bars[-1]["time"],
                  h1_bars[-1]["close"], "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(2, f"H1 Liquidity Purge ({purge_dir.upper()})",
              h1_bars[-1]["time"],
              h1_bars[-1]["close"] if purge_dir == "bullish" else h1_bars[-1]["high"] if purge_dir == "bearish" else 0,
              "H1")

    # ── Step 3: 1M iFVG entry after purge ──────────────────────────
    purged_level = buy_side if purge_dir == "bearish" else sell_side
    h1_close_time = h1_bars[-1]["time"]

    for i in range(3, len(m1_bars)):
        if m1_bars[i]["time"] < h1_close_time:
            continue
        if i > len(m1_bars) - 3:
            break

        bar = m1_bars[i]

        # ── Wait for opposite sweep on 1M ───────────────────────
        lookback = max(0, i - 10)
        recent_high = max(b["high"] for b in m1_bars[lookback:i])
        recent_low = min(b["low"] for b in m1_bars[lookback:i])

        if purge_dir == "bullish":
            if bar["low"] < recent_low:
                log.event(3, "1M Sweep after Purge (Low)",
                          bar["time"], bar["low"], "M1")
            else:
                continue
        else:
            if bar["high"] > recent_high:
                log.event(3, "1M Sweep after Purge (High)",
                          bar["time"], bar["high"], "M1")
            else:
                continue

        # ── iFVG reversal entry ────────────────────────────────
        fvgs = detect_fvg(m1_bars[max(0, i - 6):i + 1])
        if not fvgs:
            continue

        for fvg in fvgs:
            if purge_dir == "bullish" and bar["close"] > fvg["top"]:
                log.event(4, "iFVG Reversal Entry (Long)",
                          bar["time"], bar["close"], "M1")

                sl = round(bar["low"] * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"h1_purge": purge_dir,
                           "purged_level": purged_level,
                           "management": "Discretionary RR"})
                break

            if purge_dir == "bearish" and bar["close"] < fvg["bottom"]:
                log.event(4, "iFVG Reversal Entry (Short)",
                          bar["time"], bar["close"], "M1")

                sl = round(bar["high"] * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"h1_purge": purge_dir,
                           "purged_level": purged_level,
                           "management": "Discretionary RR"})
                break
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
