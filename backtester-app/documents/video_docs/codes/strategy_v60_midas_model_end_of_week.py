"""
Strategy: Midas Model End of Week (Inversion Entry Focus)
Source: Faiz SMC ("The Midas Model A+ Setup - GOLD Trade Breakdown")
Video: https://www.youtube.com/watch?v=Leh2moBQUpk

Core Concept:
  Gold. End of week recap. 15M unswept H/L (post-12PM NY prev day).
  8PM sweep. 1M W-shape MSS. If MSS is unclear/aggressive, wait for
  FVG inversion within dealing range before entering.
  Max 2 trades (8PM + 9PM), before midnight. 1:2 target, BE at 1:1.
  If 8PM trade missed, look for 9PM trade.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "MidasModelEndOfWeek"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M15", "M1"]


def find_unswept_levels(m15_bars, deadline_hour, lookback=10):
    pre = [b for b in m15_bars if get_ny_time(b["time"]).hour < deadline_hour]
    if len(pre) < 3:
        return None, None, None, None
    recent = pre[-lookback:]
    high_bar = max(recent, key=lambda b: b["high"])
    low_bar = min(recent, key=lambda b: b["low"])
    return high_bar["high"], low_bar["low"], high_bar["time"], low_bar["time"]


def find_fvgs_in_range(bars, start_idx, end_idx):
    seg = bars[max(0, start_idx):min(len(bars), end_idx + 1)]
    return detect_fvg(seg)


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m15_bars or not m1_bars:
        print("No data found")
        return

    for session_hour, session_label in [(20, "8PM"), (21, "9PM")]:
        pre_high, pre_low, pre_high_time, pre_low_time = find_unswept_levels(
            m15_bars, session_hour
        )
        if pre_high is None:
            continue

        log.event(1, f"{session_label}: Unswept Levels (15M)",
                  pre_high_time or m15_bars[-1]["time"],
                  pre_high, "M15",
                  f"High={pre_high:.2f}, Low={pre_low:.2f}")

        swept = False
        sweep_side = None
        sweep_idx = None
        trade_taken = False

        for j in range(len(m1_bars)):
            ny = get_ny_time(m1_bars[j]["time"])
            if ny.hour < session_hour:
                continue
            if ny.hour >= session_hour + 3:
                break
            if trade_taken:
                break

            bar = m1_bars[j]

            if not swept:
                if bar["low"] < pre_low:
                    log.event(2, f"{session_label}: Low Swept",
                              bar["time"], bar["low"], "M1")
                    swept = True
                    sweep_side = "low"
                    sweep_idx = j
                elif bar["high"] > pre_high:
                    log.event(2, f"{session_label}: High Swept",
                              bar["time"], bar["high"], "M1")
                    swept = True
                    sweep_side = "high"
                    sweep_idx = j
                continue

            if sweep_idx is None:
                continue

            seg = m1_bars[max(0, j - 7):j + 1]
            if len(seg) < 4:
                continue

            bar_now = m1_bars[j]
            recent_high = max(b["high"] for b in seg[:-1])
            recent_low = min(b["low"] for b in seg[:-1])

            clean_mss = None
            if sweep_side == "low":
                if bar_now["close"] > bar_now["open"] and bar_now["close"] > recent_high:
                    clean_mss = "bullish"
            else:
                if bar_now["close"] < bar_now["open"] and bar_now["close"] < recent_low:
                    clean_mss = "bearish"

            if clean_mss is not None:
                log.event(3, f"{session_label}: Clean MSS ({clean_mss.upper()})",
                          bar_now["time"], bar_now["close"], "M1")

                if clean_mss == "bullish":
                    sl = round(bar_now["low"] * 0.9998, 5)
                    tp = round(bar_now["close"] + (bar_now["close"] - sl) * 2, 5)
                    log.trade("LONG", bar_now["close"], sl, tp,
                              bar_now["time"], symbol, STRATEGY_NAME,
                              {"session": session_label,
                               "entry_type": "direct_mss",
                               "management": "BE at 1:1, TP at 1:2"})
                else:
                    sl = round(bar_now["high"] * 1.0002, 5)
                    tp = round(bar_now["close"] - (sl - bar_now["close"]) * 2, 5)
                    log.trade("SHORT", bar_now["close"], sl, tp,
                              bar_now["time"], symbol, STRATEGY_NAME,
                              {"session": session_label,
                               "entry_type": "direct_mss",
                               "management": "BE at 1:1, TP at 1:2"})
                trade_taken = True
                break

            fvgs = find_fvgs_in_range(m1_bars, sweep_idx, j)
            if not fvgs:
                continue

            for fvg in fvgs:
                if sweep_side == "low" and bar_now["close"] > fvg["top"]:
                    log.event(3, f"{session_label}: FVG Inversion Entry (Long)",
                              bar_now["time"], bar_now["close"], "M1",
                              f"FVG inversed: {fvg['top']:.2f}-{fvg['bottom']:.2f}")
                    sl = round(bar_now["low"] * 0.9998, 5)
                    tp = round(bar_now["close"] + (bar_now["close"] - sl) * 2, 5)
                    log.trade("LONG", bar_now["close"], sl, tp,
                              bar_now["time"], symbol, STRATEGY_NAME,
                              {"session": session_label,
                               "entry_type": "fvg_inversion",
                               "management": "BE at 1:1, TP at 1:2"})
                    trade_taken = True
                    break
                if sweep_side == "high" and bar_now["close"] < fvg["bottom"]:
                    log.event(3, f"{session_label}: FVG Inversion Entry (Short)",
                              bar_now["time"], bar_now["close"], "M1",
                              f"FVG inversed: {fvg['top']:.2f}-{fvg['bottom']:.2f}")
                    sl = round(bar_now["high"] * 1.0002, 5)
                    tp = round(bar_now["close"] - (sl - bar_now["close"]) * 2, 5)
                    log.trade("SHORT", bar_now["close"], sl, tp,
                              bar_now["time"], symbol, STRATEGY_NAME,
                              {"session": session_label,
                               "entry_type": "fvg_inversion",
                               "management": "BE at 1:1, TP at 1:2"})
                    trade_taken = True
                    break

                if trade_taken:
                    break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
