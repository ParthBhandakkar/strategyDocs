"""
Strategy: Finding The Correct Draw On Liquidity With 96% Accuracy
Source: Faiz SMC
Video: http://www.youtube.com/watch?v=vT_xPTnsZ5s

Core Concept:
  15M London session range (2AM–5AM NY). Sweep of session high or low
  before NY open. Apply Fib 0.79 retracement. 1M candle close beyond
  0.79 confirms direction toward opposite session boundary.
  Extreme FVG within dealing range for entry. 1:1.5 target,
  move SL to BE at 1:1.5.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "DrawOnLiquidity96"
SYMBOL = "MNQ"
TIMEFRAMES = ["M15", "M1"]


def get_session_range(m15_bars, start_hour, end_hour):
    """Return (high, low, first_bar_time) for bars in [start_hour, end_hour)."""
    sess = [
        b for b in m15_bars
        if start_hour <= get_ny_time(b["time"]).hour < end_hour
    ]
    if not sess:
        return None, None, None
    high = max(b["high"] for b in sess)
    low = min(b["low"] for b in sess)
    return high, low, sess[0]["time"]


def fib_079(low_price, high_price):
    """Return the 0.79 Fibonacci retracement level."""
    return low_price + (high_price - low_price) * 0.79


def find_extreme_fvg(bars: list, direction: str):
    """Find the most extreme FVG in the given direction within bars."""
    fvgs = [f for f in detect_fvg(bars) if f["direction"] == direction]
    if not fvgs:
        return None
    if direction == "bullish":
        # Highest bottom — closest to market
        return max(fvgs, key=lambda f: f["bottom"])
    else:
        # Lowest top — closest to market
        return min(fvgs, key=lambda f: f["top"])


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m15_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: London session range (2AM – 5AM NY) ────────────────
    sess_high, sess_low, sess_start = get_session_range(m15_bars, 2, 5)
    if sess_high is None:
        log.event(0, "London session range not found", m15_bars[-1]["time"],
                  0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, "15M London Session Range", sess_start,
              sess_high, "M15",
              f"High={sess_high:.2f}, Low={sess_low:.2f}")

    # ── Step 2: Find sweep before NY open (before 9:30) ────────────
    sweep_bar = None
    sweep_type = None  # "high_swept" = bearish draw, "low_swept" = bullish draw

    for i, b in enumerate(m1_bars):
        ny = get_ny_time(b["time"])
        if ny.hour >= 9 and ny.minute >= 30:
            break
        if b["high"] > sess_high:
            sweep_bar = b
            sweep_type = "high_swept"
            break
        if b["low"] < sess_low:
            sweep_bar = b
            sweep_type = "low_swept"
            break

    if sweep_bar is None:
        log.event(2, "No sweep before NY open", m1_bars[-1]["time"], 0, "M1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    if sweep_type == "high_swept":
        log.event(2, "London High Swept (Bearish Draw)", sweep_bar["time"],
                  sweep_bar["high"], "M1",
                  "Draw on liquidity = session low")
        draw_direction = "bearish"
    else:
        log.event(2, "London Low Swept (Bullish Draw)", sweep_bar["time"],
                  sweep_bar["low"], "M1",
                  "Draw on liquidity = session high")
        draw_direction = "bullish"

    # ── Step 3: Fib 0.79 ────────────────────────────────────────────
    fib_level = fib_079(sess_low, sess_high)
    log.event(3, f"Fib 0.79 Level = {fib_level:.2f}", sweep_bar["time"],
              fib_level, "M1",
              f"Direction: price must close {'below' if draw_direction == 'bearish' else 'above'} 0.79")

    # ── Step 4: Wait for 1M close beyond 0.79 + extreme FVG entry ──
    sweep_idx = next(
        i for i, b in enumerate(m1_bars) if b["time"] == sweep_bar["time"]
    )

    trade_taken = False
    waiting_for_break = True

    for i in range(sweep_idx + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])

        if trade_taken:
            break

        # Limit to NY morning session
        if ny.hour >= 11 and ny.minute > 30:
            break

        # ── Wait for close beyond 0.79 ──────────────────────────────
        if waiting_for_break:
            if draw_direction == "bullish":
                confirmed = bar["close"] > fib_level and bar["close"] > bar["open"]
            else:
                confirmed = bar["close"] < fib_level and bar["close"] < bar["open"]

            if not confirmed:
                continue

            waiting_for_break = False
            log.event(4, f"1M Candle Confirmed Beyond 0.79 Fib",
                      bar["time"], bar["close"], "M1",
                      f"Price closed "
                      f"{'above' if draw_direction == 'bullish' else 'below'} "
                      f"0.79, draw = session {'high' if draw_direction == 'bullish' else 'low'}")

        # ── Find extreme FVG for entry ──────────────────────────────
        seg = m1_bars[max(0, i - 15):i + 1]
        extreme_fvg = find_extreme_fvg(seg, draw_direction)

        if extreme_fvg is None:
            continue

        # Check body close inversion of this specific FVG
        if draw_direction == "bullish":
            if not (bar["close"] > extreme_fvg["top"] and bar["close"] > bar["open"]):
                continue
            entry = extreme_fvg["top"]
            sl = round(sess_low * 0.9998, 5)
            tp = round(entry + (entry - sl) * 1.5, 5)

            log.event(5, "Extreme FVG Entry (Bullish)", bar["time"],
                      entry, "M1",
                      f"FVG: {extreme_fvg['top']:.2f}-{extreme_fvg['bottom']:.2f}")

            log.trade("LONG", entry, sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"fib_079": round(fib_level, 2),
                       "sess_high": sess_high, "sess_low": sess_low,
                       "draw_to": "session high",
                       "extreme_fvg_top": extreme_fvg["top"],
                       "extreme_fvg_bottom": extreme_fvg["bottom"],
                       "management": "BE at 1:1.5"})
        else:
            if not (bar["close"] < extreme_fvg["bottom"] and bar["close"] < bar["open"]):
                continue
            entry = extreme_fvg["bottom"]
            sl = round(sess_high * 1.0002, 5)
            tp = round(entry - (sl - entry) * 1.5, 5)

            log.event(5, "Extreme FVG Entry (Bearish)", bar["time"],
                      entry, "M1",
                      f"FVG: {extreme_fvg['top']:.2f}-{extreme_fvg['bottom']:.2f}")

            log.trade("SHORT", entry, sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"fib_079": round(fib_level, 2),
                       "sess_high": sess_high, "sess_low": sess_low,
                       "draw_to": "session low",
                       "extreme_fvg_top": extreme_fvg["top"],
                       "extreme_fvg_bottom": extreme_fvg["bottom"],
                       "management": "BE at 1:1.5"})

        trade_taken = True
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
