"""
Strategy: Gold Scalping Strategy For Beginners (FULL GUIDE)
Source: Faiz SMC
Video: https://www.youtube.com/watch?v=3e2xQo-dsOI

Core Concept:
  H1 key levels (highs/lows/FVGs). Price taps H1 level → 5M dealing range.
  5M FVG inversion entry. Max 3 trades/day (1 per session). Stop on first win.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "GoldScalpingBeginners"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["H1", "M5"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m5_bars = get_bars(data_dir, symbol, "M5")

    if not h1_bars or not m5_bars:
        print("No data found")
        return

    # ── Step 1: H1 key levels ───────────────────────────────────────
    h1_highs = []
    h1_lows = []
    h1_fvgs = detect_fvg(h1_bars)

    for i in range(1, len(h1_bars) - 1):
        if h1_bars[i]["high"] > h1_bars[i - 1]["high"] and h1_bars[i]["high"] > h1_bars[i + 1]["high"]:
            h1_highs.append((h1_bars[i]["time"], h1_bars[i]["high"]))
        if h1_bars[i]["low"] < h1_bars[i - 1]["low"] and h1_bars[i]["low"] < h1_bars[i + 1]["low"]:
            h1_lows.append((h1_bars[i]["time"], h1_bars[i]["low"]))

    log.event(1, "H1 Key Levels + FVGs", h1_bars[-1]["time"],
              h1_bars[-1]["close"], "H1",
              f"Swings: {len(h1_highs)}H/{len(h1_lows)}L, FVGs: {len(h1_fvgs)}")

    if not h1_fvgs:
        log.event(2, "No H1 FVG found", h1_bars[-1]["time"], 0, "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── Session management ──────────────────────────────────────────
    trades_today = 0
    MAX_TRADES = 3
    trade_taken = False

    for i in range(10, len(m5_bars)):
        bar = m5_bars[i]
        ny = get_ny_time(bar["time"])
        if trade_taken:
            # Stop on first win per session
            continue
        if trades_today >= MAX_TRADES:
            break

        # Determine session
        if ny.hour < 3:
            session = "asia"
        elif ny.hour < 8:
            session = "london"
        elif ny.hour < 17:
            session = "ny"
        else:
            continue

        # ── Step 2: Check if price taps H1 level/FVG ────────────────
        tapped = False
        target_level = 0.0
        target_dir = ""

        for fvg in h1_fvgs:
            fvg_top, fvg_bottom = fvg["top"], fvg["bottom"]
            if fvg_bottom <= bar["low"] <= fvg_top or fvg_bottom <= bar["high"] <= fvg_top:
                tapped = True
                target_dir = fvg["direction"]
                target_level = fvg_top if target_dir == "bearish" else fvg_bottom
                break

        if not tapped:
            continue

        # ── Step 3: 5M inversion ──────────────────────────────────
        seg = m5_bars[max(0, i - 10):i + 1]
        seg_fvgs = detect_fvg(seg)

        # Check all 5M FVGs in range are inverted
        all_inverted = True
        for sf in seg_fvgs:
            if target_dir == "bullish":
                if not (bar["close"] > sf["top"] and bar["close"] > bar["open"]):
                    all_inverted = False
                    break
            else:
                if not (bar["close"] < sf["bottom"] and bar["close"] < bar["open"]):
                    all_inverted = False
                    break

        if not all_inverted or not seg_fvgs:
            continue

        log.event(3, f"{session.upper()} - All 5M FVGs Inverted ({len(seg_fvgs)})",
                  bar["time"], bar["close"], "M5")

        if target_dir == "bullish":
            sl = round(bar["low"] * 0.9998, 5)
            tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
            log.trade("LONG", bar["close"], sl, tp, bar["time"], symbol,
                      STRATEGY_NAME,
                      {"session": session, "max_trades_day": MAX_TRADES,
                       "management": "BE at nearest liquidity, 30% partial at 1:1"})
        else:
            sl = round(bar["high"] * 1.0002, 5)
            tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
            log.trade("SHORT", bar["close"], sl, tp, bar["time"], symbol,
                      STRATEGY_NAME,
                      {"session": session, "max_trades_day": MAX_TRADES,
                       "management": "BE at nearest liquidity, 30% partial at 1:1"})

        trades_today += 1
        trade_taken = True
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
