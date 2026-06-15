"""
Strategy: Simple ICT Liquidity Trading Strategy
Source: Faiz SMC ("Simple ICT Liquidity Trading Strategy That Makes $500/Day")
Video: https://www.youtube.com/watch?v=Zqw2tDMGqqA

Core Concept:
  4H swing H/L identification (3-candle swing). Mark H/L of 3rd candle.
  Wait for sweep of either level within the next 4H candle.
  5M MSS with body closure. Entry from OB or FVG.
  SL above/below sweep. BE at 1:1, partial at 1:2.
  Invalid if no sweep within 4H candle window or no MSS.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "SimpleICTLiquidity"
SYMBOL = "NQ"
TIMEFRAMES = ["H4", "M5"]


def find_swing_levels(bars_h4: list):
    """
    Find the most recent 3-candle swing high and swing low.
    Returns (swing_high, swing_low, high_time, low_time).
    """
    if len(bars_h4) < 4:
        return None, None, None, None

    last_3 = bars_h4[-4:-1]

    # Swing high: middle bar has highest high
    if last_3[1]["high"] > last_3[0]["high"] and last_3[1]["high"] > last_3[2]["high"]:
        swing_high = last_3[1]["high"]
        high_time = last_3[1]["time"]
    else:
        swing_high = None
        high_time = None

    # Swing low: middle bar has lowest low
    if last_3[1]["low"] < last_3[0]["low"] and last_3[1]["low"] < last_3[2]["low"]:
        swing_low = last_3[1]["low"]
        low_time = last_3[1]["time"]
    else:
        swing_low = None
        low_time = None

    return swing_high, swing_low, high_time, low_time


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "H4")
    m5_bars = get_bars(data_dir, symbol, "M5")

    if not h4_bars or not m5_bars:
        print("No data found")
        return

    # ── Step 1-2: Identify swing + mark H/L of 3rd candle ──────────
    swing_high, swing_low, high_time, low_time = find_swing_levels(h4_bars)

    if swing_high is None and swing_low is None:
        log.event(1, "No swing formation found", h4_bars[-1]["time"],
                  0, "H4")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, "4H Swing Levels", high_time or low_time or h4_bars[-1]["time"],
              swing_high or swing_low, "H4",
              f"Swing High={swing_high}, Swing Low={swing_low}")

    # Determine which level to trade: sweep of old level within new candle
    current_candle_start = h4_bars[-1]["time"]
    current_high = h4_bars[-1]["high"]
    current_low = h4_bars[-1]["low"]

    swept = False
    sweep_side = None
    sweep_level = None

    # ── Step 3: Scan 5M within current 4H candle ────────────────────
    for i in range(1, len(m5_bars)):
        bar = m5_bars[i]
        ny = get_ny_time(bar["time"])

        # Only within current 4H candle (Killzone for higher win rate)
        if ny.hour < 8 or ny.hour > 16:
            continue

        # Check if 5M bar is within the current 4H period
        if bar["time"] < current_candle_start:
            continue

        # If we've moved past the current 4H candle, stop
        if i + 1 < len(m5_bars) and \
           get_ny_time(m5_bars[i + 1]["time"]).hour >= (ny.hour + 4):
            break

        # ── Sweep detection ─────────────────────────────────────
        if not swept:
            if swing_high and bar["high"] > swing_high:
                log.event(2, "Swing High Swept", bar["time"],
                          bar["high"], "M5")
                swept = True
                sweep_side = "short"
                sweep_level = swing_high
                sweep_idx = i
            elif swing_low and bar["low"] < swing_low:
                log.event(2, "Swing Low Swept", bar["time"],
                          bar["low"], "M5")
                swept = True
                sweep_side = "long"
                sweep_level = swing_low
                sweep_idx = i
            continue

        # ── After sweep: MSS with body closure ──────────────────
        seg = m5_bars[max(0, i - 7):i + 1]
        if len(seg) < 3:
            continue

        bar_now = m5_bars[i]
        recent_high = max(b["high"] for b in seg[:-1])
        recent_low = min(b["low"] for b in seg[:-1])

        mss_ok = False
        if sweep_side == "long":
            if bar_now["close"] > bar_now["open"] and bar_now["close"] > recent_high:
                mss_ok = True
        else:
            if bar_now["close"] < bar_now["open"] and bar_now["close"] < recent_low:
                mss_ok = True

        if not mss_ok:
            continue

        log.event(3, f"MSS with Body Closure ({'LONG' if sweep_side == 'long' else 'SHORT'})",
                  bar_now["time"], bar_now["close"], "M5")

        # ── Entry from OB/FVG ──────────────────────────────────
        fvgs = detect_fvg(seg)

        if sweep_side == "long":
            sl = round(bar_now["low"] * 0.9998, 5)
            tp = round(bar_now["close"] + (bar_now["close"] - sl) * 2, 5)
            log.trade("LONG", bar_now["close"], sl, tp, bar_now["time"],
                      symbol, STRATEGY_NAME,
                      {"swing_level": sweep_level,
                       "entry_type": "FVG" if fvgs else "MSS",
                       "management": "BE at 1:1, partial at 1:2"})
        else:
            sl = round(bar_now["high"] * 1.0002, 5)
            tp = round(bar_now["close"] - (sl - bar_now["close"]) * 2, 5)
            log.trade("SHORT", bar_now["close"], sl, tp, bar_now["time"],
                      symbol, STRATEGY_NAME,
                      {"swing_level": sweep_level,
                       "entry_type": "FVG" if fvgs else "MSS",
                       "management": "BE at 1:1, partial at 1:2"})
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
