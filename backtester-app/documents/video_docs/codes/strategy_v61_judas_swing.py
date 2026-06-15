"""
Strategy: 8PM/9PM Judas Swing (Gold/AUDJPY)
Source: Faiz SMC ("Give me 20 mins & I'll teach you best GOLD trading strategy..")
Video: https://www.youtube.com/watch?v=RZgRjnqVnzk

Core Concept:
  Gold or AUDJPY. 15M unswept H/L before 8PM/9PM NY. Sweep → 1M MSS
  entry targeting opposite side 15M level. Only one trade active at a
  time. 5M variation: after 8PM/9:30AM, obvious liquidity run → FVG
  inversion entry. 1:2 RR, partial at 1:1. Invalid if closest
  liquidity level hit before entry.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "JudasSwing"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M15", "M5", "M1"]


def find_unswept_15m_levels(m15_bars, deadline_hour, lookback=10):
    pre = [b for b in m15_bars if get_ny_time(b["time"]).hour < deadline_hour]
    if len(pre) < 3:
        return None, None, None, None
    recent = pre[-lookback:]
    high_bar = max(recent, key=lambda b: b["high"])
    low_bar = min(recent, key=lambda b: b["low"])
    return high_bar["high"], low_bar["low"], high_bar["time"], low_bar["time"]


def run_15m_1m_model(m1_bars, log, session_hour, session_label, symbol,
                     pre_high, pre_low):
    """Run the 15M/1M Judas Swing model for a given session."""
    swept = False
    sweep_side = None

    for j in range(0, len(m1_bars)):
        ny = get_ny_time(m1_bars[j]["time"])
        if ny.hour < session_hour:
            continue
        if ny.hour >= session_hour + 3:
            break

        bar = m1_bars[j]

        if not swept:
            if bar["low"] < pre_low:
                log.event(2, f"{session_label} 15M/1M: Low Swept",
                          bar["time"], bar["low"], "M1")
                swept = True
                sweep_side = "low"
            elif bar["high"] > pre_high:
                log.event(2, f"{session_label} 15M/1M: High Swept",
                          bar["time"], bar["high"], "M1")
                swept = True
                sweep_side = "high"
            continue

        # MSS detection
        seg = m1_bars[max(0, j - 7):j + 1]
        if len(seg) < 4:
            continue

        bar_now = m1_bars[j]
        recent_high = max(b["high"] for b in seg[:-1])
        recent_low = min(b["low"] for b in seg[:-1])

        mss_dir = None
        if sweep_side == "low":
            if bar_now["close"] > bar_now["open"] and bar_now["close"] > recent_high:
                mss_dir = "bullish"
        else:
            if bar_now["close"] < bar_now["open"] and bar_now["close"] < recent_low:
                mss_dir = "bearish"

        if mss_dir is None:
            continue

        log.event(3, f"{session_label} 15M/1M: MSS ({mss_dir.upper()})",
                  bar_now["time"], bar_now["close"], "M1")

        if sweep_side == "low":
            sl = round(bar_now["low"] * 0.9998, 5)
            tp = round(pre_high, 5)
            log.trade("LONG", bar_now["close"], sl, tp, bar_now["time"],
                      symbol, STRATEGY_NAME,
                      {"session": session_label, "model": "15M/1M",
                       "target_level": pre_high,
                       "management": "Partial 1:1, TP opposite level"})
        else:
            sl = round(bar_now["high"] * 1.0002, 5)
            tp = round(pre_low, 5)
            log.trade("SHORT", bar_now["close"], sl, tp, bar_now["time"],
                      symbol, STRATEGY_NAME,
                      {"session": session_label, "model": "15M/1M",
                       "target_level": pre_low,
                       "management": "Partial 1:1, TP opposite level"})
        return True

    return False


def run_5m_model(m5_bars, log, session_hour, session_label, symbol):
    """Run the 5M FVG inversion model."""
    pre_high, pre_low, pre_high_time, pre_low_time = find_unswept_15m_levels(
        m5_bars, session_hour, lookback=8
    )
    if pre_high is None:
        return False

    log.event(1, f"{session_label} 5M: Unswept Levels",
              pre_high_time or m5_bars[-1]["time"],
              pre_high, "M5",
              f"High={pre_high:.2f}, Low={pre_low:.2f}")

    swept = False
    sweep_side = None

    for i in range(0, len(m5_bars)):
        ny = get_ny_time(m5_bars[i]["time"])
        if ny.hour < session_hour:
            continue
        if ny.hour >= session_hour + 4:
            break

        bar = m5_bars[i]

        if not swept:
            if bar["low"] < pre_low:
                log.event(2, f"{session_label} 5M: Liquidity Run Low",
                          bar["time"], bar["low"], "M5")
                swept = True
                sweep_side = "low"
                sweep_idx = i
            elif bar["high"] > pre_high:
                log.event(2, f"{session_label} 5M: Liquidity Run High",
                          bar["time"], bar["high"], "M5")
                swept = True
                sweep_side = "high"
                sweep_idx = i
            continue

        # FVG inversion
        if sweep_idx is None:
            continue

        fvgs = detect_fvg(m5_bars[max(0, sweep_idx):i + 1])
        if not fvgs:
            continue

        for fvg in fvgs:
            if sweep_side == "low" and bar["close"] > fvg["top"]:
                log.event(3, f"{session_label} 5M: FVG Inversion (Long)",
                          bar["time"], bar["close"], "M5",
                          f"FVG: {fvg['top']:.2f}-{fvg['bottom']:.2f}")

                sl = round(bar["low"] * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"session": session_label, "model": "5M",
                           "fvg_top": fvg["top"], "fvg_bottom": fvg["bottom"],
                           "management": "Partial 1:1, BE at closest pool, 1:2"})
                return True

            if sweep_side == "high" and bar["close"] < fvg["bottom"]:
                log.event(3, f"{session_label} 5M: FVG Inversion (Short)",
                          bar["time"], bar["close"], "M5",
                          f"FVG: {fvg['top']:.2f}-{fvg['bottom']:.2f}")

                sl = round(bar["high"] * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"session": session_label, "model": "5M",
                           "fvg_top": fvg["top"], "fvg_bottom": fvg["bottom"],
                           "management": "Partial 1:1, BE at closest pool, 1:2"})
                return True

    return False


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    m5_bars = get_bars(data_dir, symbol, "M5")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m15_bars or not m1_bars:
        print("No data found")
        return

    # ── 8PM and 9PM sessions: only one trade total ──────────────────
    for session_hour, session_label in [(20, "8PM"), (21, "9PM")]:
        pre_high, pre_low, pre_high_time, pre_low_time = find_unswept_15m_levels(
            m15_bars, session_hour
        )
        if pre_high is None:
            continue

        log.event(1, f"{session_label} 15M: Unswept Levels",
                  pre_high_time or m15_bars[-1]["time"],
                  pre_high, "M15",
                  f"High={pre_high:.2f}, Low={pre_low:.2f}")

        if run_15m_1m_model(m1_bars, log, session_hour, session_label,
                            symbol, pre_high, pre_low):
            break

    # ── 5M Model: 8PM (Asia) and 9:30AM (NY) ───────────────────────
    run_5m_model(m5_bars, log, 20, "8PM", symbol)
    run_5m_model(m5_bars, log, 9, "9:30AM", symbol)

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
