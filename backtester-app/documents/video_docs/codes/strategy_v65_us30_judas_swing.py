"""
Strategy: US30 Judas Swing
Source: Faiz SMC ("Best ICT Judas Swing Trading Strategy With 79% Winrate!")
Video: https://www.youtube.com/watch?v=s0jk8ENNkjw

Core Concept:
  US30-specific. Before 9:30 AM NY, mark most recent 15M high and low.
  After 9:30 AM open, drop to 1M. Wait for sweep of 15M level.
  Look for MSS with displacement (FVG). Enter from FVG or breaker block.
  SL below sweep low. Target opposite 15M level.
  30% partial at 1:1, BE at 1:1.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "US30JudasSwing"
SYMBOL = "US30"
TIMEFRAMES = ["M15", "M1"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m15_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: Pre-9:30 AM 15M levels ──────────────────────────────
    pre_m15 = [b for b in m15_bars
               if get_ny_time(b["time"]).hour < 9]
    if len(pre_m15) < 3:
        log.event(1, "Insufficient pre-9:30 data", "", 0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    pre_high = max(b["high"] for b in pre_m15[-6:])
    pre_low = min(b["low"] for b in pre_m15[-6:])
    pre_time = pre_m15[-1]["time"]

    log.event(1, "Pre-9:30 15M Levels", pre_time, pre_high, "M15",
              f"High={pre_high:.2f}, Low={pre_low:.2f}")

    # ── Step 2: Post-9:30 AM 1M sweep + MSS + entry ─────────────────
    swept = False
    sweep_side = None

    for i in range(0, len(m1_bars)):
        ny = get_ny_time(m1_bars[i]["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11 and ny.minute > 30:
            break

        bar = m1_bars[i]

        # ── Sweep detection ─────────────────────────────────────
        if not swept:
            if bar["low"] < pre_low:
                log.event(2, "Low Swept", bar["time"], bar["low"], "M1")
                swept = True
                sweep_side = "low"
            elif bar["high"] > pre_high:
                log.event(2, "High Swept", bar["time"], bar["high"], "M1")
                swept = True
                sweep_side = "high"
            continue

        # ── After sweep: MSS with displacement ──────────────────
        seg = m1_bars[max(0, i - 7):i + 1]
        if len(seg) < 4:
            continue

        bar_now = m1_bars[i]
        recent_high = max(b["high"] for b in seg[:-1])
        recent_low = min(b["low"] for b in seg[:-1])

        # Check for displacement (FVG in the move)
        has_fvg = False
        for k in range(1, len(seg) - 1):
            if sweep_side == "low" and seg[k]["low"] > seg[k - 1]["high"]:
                has_fvg = True
                break
            if sweep_side == "high" and seg[k]["high"] < seg[k - 1]["low"]:
                has_fvg = True
                break

        mss_dir = None
        if sweep_side == "low":
            if bar_now["close"] > bar_now["open"] and bar_now["close"] > recent_high:
                mss_dir = "bullish"
        else:
            if bar_now["close"] < bar_now["open"] and bar_now["close"] < recent_low:
                mss_dir = "bearish"

        if mss_dir is None:
            continue

        log.event(3, f"MSS with {'Displacement' if has_fvg else 'Structure Shift'} "
                  f"({mss_dir.upper()})", bar_now["time"],
                  bar_now["close"], "M1")

        if mss_dir == "bullish":
            sl = round(bar_now["low"] * 0.9998, 5)
            tp = round(pre_high, 5)
            log.trade("LONG", bar_now["close"], sl, tp, bar_now["time"],
                      symbol, STRATEGY_NAME,
                      {"pre_low": pre_low, "pre_high": pre_high,
                       "has_displacement": has_fvg,
                       "management": "30% partial at 1:1, BE at 1:1, "
                                     "TP opposite 15M level"})
        else:
            sl = round(bar_now["high"] * 1.0002, 5)
            tp = round(pre_low, 5)
            log.trade("SHORT", bar_now["close"], sl, tp, bar_now["time"],
                      symbol, STRATEGY_NAME,
                      {"pre_low": pre_low, "pre_high": pre_high,
                       "has_displacement": has_fvg,
                       "management": "30% partial at 1:1, BE at 1:1, "
                                     "TP opposite 15M level"})
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
