"""
Strategy: Easy ICT Scalping (NQ/ES)
Source: Faiz SMC ("Easy ICT Scalping Trading Strategy That Makes $1,000/Day")
Video: https://www.youtube.com/watch?v=s9lsHH1WwKg

Core Concept:
  NQ/ES. Before 9:30 AM, identify 15M order flow + FVG.
  After open, wait for price to tap 15M FVG. Drop to 1M.
  Look for SMT divergence (NQ/ES). 1M FVG inversion entry.
  Avoid consolidation. BE at closest H/L. 1st partial at 1:1
  (or 0.7 if consolidating), 2nd partial at 1:2.
  Final TP at next equal highs/lows.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "EasyICTScalp"
SYMBOL = "NQ"
TIMEFRAMES = ["M15", "M1"]


def check_smt(nq_bars: list, idx: int, es_bars: list):
    if not es_bars or len(es_bars) < 8:
        return None

    nq_seg = nq_bars[max(0, idx - 8):idx + 1]
    es_seg = es_bars[-8:]

    bar = nq_bars[idx]
    nq_low = min(b["low"] for b in nq_seg)
    nq_high = max(b["high"] for b in nq_seg)
    es_low = min(b["low"] for b in es_seg)
    es_high = max(b["high"] for b in es_seg)

    if bar["low"] == nq_low and bar["low"] < nq_seg[-2]["low"] \
       and es_low >= es_seg[-2]["low"]:
        return "bullish"
    if bar["high"] == nq_high and bar["high"] > nq_seg[-2]["high"] \
       and es_high <= es_seg[-2]["high"]:
        return "bearish"

    return None


def detect_consolidation(bars: list, idx: int, lookback: int = 10):
    """Check if market is consolidating (tight range)."""
    seg = bars[max(0, idx - lookback):idx + 1]
    if len(seg) < 5:
        return False

    avg_range = sum(b["high"] - b["low"] for b in seg) / len(seg)
    total_range = max(b["high"] for b in seg) - min(b["low"] for b in seg)

    return total_range < avg_range * 1.5


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")
    es_m1_bars = get_bars(data_dir, "ES", "M1")

    if not m15_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1-2: 15M order flow + FVG ──────────────────────────────
    m15_fvgs = detect_fvg(m15_bars)

    if not m15_fvgs:
        log.event(1, "No 15M FVG Found", m15_bars[-1]["time"], 0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, "15M FVG Levels", m15_bars[-1]["time"], 0, "M15",
              f"Count: {len(m15_fvgs)}")

    # ── Step 3-4: Post-9:30 AM ──────────────────────────────────────
    has_tapped_fvg = False
    consolidating = False

    for i in range(5, len(m1_bars)):
        ny = get_ny_time(m1_bars[i]["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11 and ny.minute > 30:
            break

        bar = m1_bars[i]

        # ── Detect consolidation ────────────────────────────────
        consolidating = detect_consolidation(m1_bars, i)

        # ── Price taps 15M FVG ──────────────────────────────────
        if not has_tapped_fvg:
            for fvg in m15_fvgs:
                if fvg["bottom"] <= bar["low"] <= fvg["top"] \
                   or fvg["bottom"] <= bar["high"] <= fvg["top"]:
                    has_tapped_fvg = True
                    log.event(2, "Price Tapped 15M FVG", bar["time"],
                              bar["close"], "M1",
                              f"FVG: {fvg['top']:.2f}-{fvg['bottom']:.2f}")
                    break

        if not has_tapped_fvg:
            continue

        # ── SMT divergence ──────────────────────────────────────
        smt_dir = check_smt(m1_bars, i, es_m1_bars)
        if smt_dir is None:
            continue

        log.event(3, f"SMT Divergence ({smt_dir.upper()})",
                  bar["time"], bar["close"], "M1", "NQ/ES")

        # ── 1M FVG inversion ────────────────────────────────────
        fvgs = detect_fvg(m1_bars[max(0, i - 8):i + 1])
        if not fvgs:
            continue

        for fvg in fvgs:
            if smt_dir == "bullish" and bar["close"] > fvg["top"]:
                log.event(4, "1M FVG Inversion (Long)", bar["time"],
                          bar["close"], "M1")

                sl = round(bar["low"] * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)

                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"setup": "EasyICTScalp",
                           "tapped_15m_fvg": True,
                           "consolidating": consolidating,
                           "partial_target": "0.7" if consolidating else "1.0",
                           "management": "BE at closest H/L, partial at "
                                         f"{'0.7' if consolidating else '1:1'}, "
                                         "TP at equal H/Ls"})
                break

            if smt_dir == "bearish" and bar["close"] < fvg["bottom"]:
                log.event(4, "1M FVG Inversion (Short)", bar["time"],
                          bar["close"], "M1")

                sl = round(bar["high"] * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)

                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"setup": "EasyICTScalp",
                           "tapped_15m_fvg": True,
                           "consolidating": consolidating,
                           "partial_target": "0.7" if consolidating else "1.0",
                           "management": "BE at closest H/L, partial at "
                                         f"{'0.7' if consolidating else '1:1'}, "
                                         "TP at equal H/Ls"})
                break
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
