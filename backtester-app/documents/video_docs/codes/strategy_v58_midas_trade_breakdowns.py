"""
Strategy: Midas Model Trade Breakdowns (Gold 8PM/9PM)
Source: Faiz SMC ("The Midas Model A+ Setup - GOLD Trade Breakdown")
Video: https://www.youtube.com/watch?v=Ai0-TGDHoZo

Core Concept:
  Gold. 15M unswept H/L before 8PM NY. After 8PM open, wait for sweep.
  Drop to 1M. Look for W-shaped MSS (sweep + immediate recovery)
  that breaks structure and leaves an FVG.
  If MSS is far from action, mark all FVGs in dealing range and enter
  on inversion. V/W-shaped recovery required — no consolidation.
  1:2 target, BE at 1:1. Max 1 trade per session. 9PM trade only
  if no active 8PM trade. All trades before midnight NY.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "MidasTradeBreakdowns"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M15", "M1"]


def find_unswept_levels(m15_bars, deadline_hour, lookback=10):
    """Find most recent unswept 15M high and low before deadline_hour NY."""
    pre = [b for b in m15_bars if get_ny_time(b["time"]).hour < deadline_hour]
    if len(pre) < 3:
        return None, None, None, None

    recent = pre[-lookback:]
    high_bar = max(recent, key=lambda b: b["high"])
    low_bar = min(recent, key=lambda b: b["low"])

    return high_bar["high"], low_bar["low"], high_bar["time"], low_bar["time"]


def detect_wshape_mss(bars, idx):
    """
    Check for W-shaped MSS: sweep of a level followed by immediate
    recovery that breaks structure and leaves an FVG.
    Returns (direction, fvg) or (None, None).
    """
    seg = bars[max(0, idx - 7):idx + 1]
    if len(seg) < 4:
        return None, None

    bar = bars[idx]
    recent_high = max(b["high"] for b in seg[:-1])
    recent_low = min(b["low"] for b in seg[:-1])

    # Bullish W-shape: strong close above recent high
    if bar["close"] > bar["open"] and bar["close"] > recent_high:
        for k in range(1, len(seg) - 1):
            if seg[k]["low"] > seg[k - 1]["high"]:
                return "bullish", {
                    "top": seg[k]["low"],
                    "bottom": seg[k - 1]["high"],
                    "direction": "bullish"
                }
        return "bullish", None

    # Bearish W-shape: strong close below recent low
    if bar["close"] < bar["open"] and bar["close"] < recent_low:
        for k in range(1, len(seg) - 1):
            if seg[k]["high"] < seg[k - 1]["low"]:
                return "bearish", {
                    "top": seg[k - 1]["low"],
                    "bottom": seg[k]["high"],
                    "direction": "bearish"
                }
        return "bearish", None

    return None, None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m15_bars or not m1_bars:
        print("No data found")
        return

    # ── Process each session ────────────────────────────────────────
    for session_hour, session_label in [(20, "8PM"), (21, "9PM")]:
        pre_high, pre_low, pre_high_time, pre_low_time = find_unswept_levels(
            m15_bars, session_hour
        )

        if pre_high is None:
            continue

        ref_time = pre_high_time or m15_bars[-1]["time"]
        log.event(1, f"{session_label}: Unswept Levels", ref_time,
                  pre_high, "M15",
                  f"High={pre_high:.2f}, Low={pre_low:.2f}")

        # Scan M1 bars for this session window
        swept = False
        found_trade = False

        for j in range(0, len(m1_bars)):
            ny = get_ny_time(m1_bars[j]["time"])

            if ny.hour < session_hour:
                continue
            if ny.hour >= session_hour + 3:
                break
            if found_trade:
                break

            bar = m1_bars[j]

            if not swept:
                if bar["low"] < pre_low:
                    log.event(2, f"{session_label}: Low Swept",
                              bar["time"], bar["low"], "M1")
                    swept = True
                    sweep_dir = "bullish"
                elif bar["high"] > pre_high:
                    log.event(2, f"{session_label}: High Swept",
                              bar["time"], bar["high"], "M1")
                    swept = True
                    sweep_dir = "bearish"
                continue

            # After sweep, look for W-shape MSS in opposite direction
            direction, fvg = detect_wshape_mss(m1_bars, j)

            if direction is None:
                continue
            if direction == sweep_dir:
                continue

            log.event(3, f"{session_label}: W-Shape MSS ({direction.upper()})",
                      bar["time"], bar["close"], "M1")

            if direction == "bullish":
                sl = round(bar["low"] * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"session": session_label,
                           "has_fvg": fvg is not None,
                           "swept_level": pre_low,
                           "management": "BE at 1:1, TP at 1:2"})
            else:
                sl = round(bar["high"] * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"session": session_label,
                           "has_fvg": fvg is not None,
                           "swept_level": pre_high,
                           "management": "BE at 1:1, TP at 1:2"})

            found_trade = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
