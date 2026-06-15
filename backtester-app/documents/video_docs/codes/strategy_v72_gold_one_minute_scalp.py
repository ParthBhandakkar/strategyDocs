"""
Strategy: Gold 1-Minute Scalping (8PM/9PM Midas Variant)
Source: Faiz SMC ("GOLD 1 Minute Trading Strategy That Actually Works..")
Video: https://www.youtube.com/watch?v=EpmNNATDxyg

Core Concept:
  Gold. Before 8PM NY, identify most recent 15M high and low.
  Wait for sweep after 8PM open. 1M MSS with displacement (FVG).
  Entry from FVG or breaker block. 4H order flow can improve win rate
  (premium/discount). 1:3 target, BE at 1:1.5, partial at 1:2.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "GoldOneMinuteScalp"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M15", "M1"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m15_bars or not m1_bars:
        print("No data found")
        return

    # ── Process 8PM and 9PM sessions ────────────────────────────────
    for session_hour, session_label in [(20, "8PM"), (21, "9PM")]:
        pre = [b for b in m15_bars
               if get_ny_time(b["time"]).hour < session_hour]
        if len(pre) < 3:
            continue

        pre_high = max(b["high"] for b in pre[-6:])
        pre_low = min(b["low"] for b in pre[-6:])

        log.event(1, f"{session_label}: 15M Pre-Levels",
                  pre[-1]["time"], pre_high, "M15",
                  f"High={pre_high:.2f}, Low={pre_low:.2f}")

        swept = False
        trade_taken = False

        for i in range(0, len(m1_bars)):
            ny = get_ny_time(m1_bars[i]["time"])
            if ny.hour < session_hour:
                continue
            if ny.hour >= session_hour + 3:
                break
            if trade_taken:
                break

            bar = m1_bars[i]

            # ── Sweep ──────────────────────────────────────────────
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

            # ── MSS with displacement (FVG) ─────────────────────────
            seg = m1_bars[max(0, i - 7):i + 1]
            if len(seg) < 4:
                continue

            bar_now = m1_bars[i]
            recent_high = max(b["high"] for b in seg[:-1])
            recent_low = min(b["low"] for b in seg[:-1])

            mss_found = False
            has_fvg = False

            if sweep_dir == "bullish":
                if bar_now["close"] > bar_now["open"] and bar_now["close"] > recent_high:
                    mss_found = True
                    for k in range(1, len(seg) - 1):
                        if seg[k]["low"] > seg[k - 1]["high"]:
                            has_fvg = True
                            break
            else:
                if bar_now["close"] < bar_now["open"] and bar_now["close"] < recent_low:
                    mss_found = True
                    for k in range(1, len(seg) - 1):
                        if seg[k]["high"] < seg[k - 1]["low"]:
                            has_fvg = True
                            break

            if not mss_found:
                continue

            log.event(3, f"{session_label}: MSS with "
                      f"{'FVG' if has_fvg else 'Structure Shift'} "
                      f"({sweep_dir.upper()})",
                      bar_now["time"], bar_now["close"], "M1")

            if sweep_dir == "bullish":
                sl = round(bar_now["low"] * 0.9998, 5)
                tp = round(bar_now["close"] + (bar_now["close"] - sl) * 3, 5)
                log.trade("LONG", bar_now["close"], sl, tp, bar_now["time"],
                          symbol, STRATEGY_NAME,
                          {"session": session_label,
                           "target_level": "recency H/L or 1:3",
                           "management": "BE at 1:1.5, partial at 1:2, "
                                         "final TP at 1:3"})
            else:
                sl = round(bar_now["high"] * 1.0002, 5)
                tp = round(bar_now["close"] - (sl - bar_now["close"]) * 3, 5)
                log.trade("SHORT", bar_now["close"], sl, tp, bar_now["time"],
                          symbol, STRATEGY_NAME,
                          {"session": session_label,
                           "target_level": "recency H/L or 1:3",
                           "management": "BE at 1:1.5, partial at 1:2, "
                                         "final TP at 1:3"})

            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
