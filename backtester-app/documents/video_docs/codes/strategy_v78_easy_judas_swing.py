"""
Strategy: Easy ICT Judas Swing (Asian/London Session)
Source: Faiz SMC ("Easy ICT Judas Swing Trading Strategy That Works! (High Winrate)")
Video: https://www.youtube.com/watch?v=-bEF1vca1Xc

Core Concept:
  EURUSD/GBPUSD only. Asian session (8PM-2AM NY) and London session
  (3AM-7AM NY). Mark session range H/L. Sweep window: Asian 2AM-3AM,
  London 7AM-8AM. 5M MSS with body closure after sweep.
  Entry from OB/FVG. BE at 1:1, partial 30%, TP at opposite range H/L.
  Invalid if no sweep in window. 1H order flow for trend filtering.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "AsianLondonJudasSwing"
SYMBOL = "EURUSD"
TIMEFRAMES = ["H1", "M5"]


def get_session_range(bars: list, start_hour: int, end_hour: int):
    """Get H/L range of a session defined by NY hour range."""
    session_bars = [
        b for b in bars
        if start_hour <= get_ny_time(b["time"]).hour < end_hour
    ]
    if len(session_bars) < 2:
        return None, None, None

    high_bar = max(session_bars, key=lambda b: b["high"])
    low_bar = min(session_bars, key=lambda b: b["low"])
    return high_bar["high"], low_bar["low"], high_bar["time"]


def check_1h_orderflow(h1_bars: list):
    """Quick 1H order flow check — 3 seconds analysis."""
    if len(h1_bars) < 4:
        return None
    recent = h1_bars[-4:]
    highs = [b["high"] for b in recent]
    lows = [b["low"] for b in recent]

    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "bullish"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "bearish"
    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m5_bars = get_bars(data_dir, symbol, "M5")

    if not m5_bars:
        print("No data found")
        return

    # ── 1H order flow (quick check) ─────────────────────────────────
    if h1_bars:
        of = check_1h_orderflow(h1_bars)
        if of:
            log.event(0, f"1H Order Flow: {of.upper()}",
                      h1_bars[-1]["time"], h1_bars[-1]["close"], "H1")

    # ── Session definitions ─────────────────────────────────────────
    sessions = [
        ("Asian", 20, 2, 2, 3),    # Range 8PM-2AM, Sweep 2AM-3AM
        ("London", 3, 7, 7, 8),     # Range 3AM-7AM, Sweep 7AM-8AM
    ]

    for ses_name, range_start, range_end, sweep_start, sweep_end in sessions:
        # ── Session range ───────────────────────────────────────
        ses_high, ses_low, ses_time = get_session_range(
            m5_bars, range_start, range_end
        )
        if ses_high is None:
            continue

        log.event(1, f"{ses_name} Range", ses_time, ses_high, "M5",
                  f"High={ses_high:.5f}, Low={ses_low:.5f}")

        # ── Scan M5 in sweep window ─────────────────────────────
        swept = False

        for i in range(1, len(m5_bars)):
            ny = get_ny_time(m5_bars[i]["time"])
            if ny.hour < sweep_start or ny.hour >= sweep_end:
                continue

            bar = m5_bars[i]

            # ── Sweep ──────────────────────────────────────────
            if not swept:
                if bar["low"] < ses_low:
                    log.event(2, f"{ses_name}: Low Swept in Window",
                              bar["time"], bar["low"], "M5")
                    swept = True
                    sweep_dir = "bullish"
                    sweep_idx = i
                elif bar["high"] > ses_high:
                    log.event(2, f"{ses_name}: High Swept in Window",
                              bar["time"], bar["high"], "M5")
                    swept = True
                    sweep_dir = "bearish"
                    sweep_idx = i
                continue

            # ── MSS with body closure ──────────────────────────
            seg = m5_bars[max(0, i - 7):i + 1]
            if len(seg) < 3:
                continue

            bar_now = m5_bars[i]
            recent_high = max(b["high"] for b in seg[:-1])
            recent_low = min(b["low"] for b in seg[:-1])

            mss_ok = False
            if sweep_dir == "bullish":
                if bar_now["close"] > bar_now["open"] and bar_now["close"] > recent_high:
                    mss_ok = True
            else:
                if bar_now["close"] < bar_now["open"] and bar_now["close"] < recent_low:
                    mss_ok = True

            if not mss_ok:
                continue

            log.event(3, f"{ses_name}: MSS ({sweep_dir.upper()})",
                      bar_now["time"], bar_now["close"], "M5")

            # ── Entry ──────────────────────────────────────────
            if sweep_dir == "bullish":
                sl = round(bar_now["low"] * 0.9998, 5)
                tp = round(ses_high, 5)
                log.trade("LONG", bar_now["close"], sl, tp, bar_now["time"],
                          symbol, STRATEGY_NAME,
                          {"session": ses_name,
                           "range_high": ses_high, "range_low": ses_low,
                           "management": "BE at 1:1, 30% partial, "
                                         "TP at opposite range H/L"})
            else:
                sl = round(bar_now["high"] * 1.0002, 5)
                tp = round(ses_low, 5)
                log.trade("SHORT", bar_now["close"], sl, tp, bar_now["time"],
                          symbol, STRATEGY_NAME,
                          {"session": ses_name,
                           "range_high": ses_high, "range_low": ses_low,
                           "management": "BE at 1:1, 30% partial, "
                                         "TP at opposite range H/L"})
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
