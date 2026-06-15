"""
Strategy: 1-Minute ICT Scalping (NQ)
Source: Faiz SMC ("Easy ICT 1 Minute Trading Strategy That Works Everyday! (High Winrate)")
Video: https://www.youtube.com/watch?v=-UcPjKlzaO0

Core Concept:
  NQ only. Daily TF for rough bias. 9:30-11:30 AM NY trading window.
  Identify 15M FVG. Drop to 1M, look for SMT divergence (NQ/ES).
  Wait for 1M FVG inversion within dealing range. Entry on close.
  A+ setup: 15M FVG tap + 1M SMT + 1M FVG inversion.
  A setup: 1M SMT + 1M FVG inversion only.
  BE at closest liquidity pool. 1st partial at 1:1, 2nd partial at 1:2.
  Final TP at pre-marked equal highs/lows.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "OneMinuteICTScalp"
SYMBOL = "NQ"
TIMEFRAMES = ["D1", "M15", "M1"]


def check_smt_divergence(nq_bars: list, idx: int, es_bars: list):
    """Check 1M SMT divergence between NQ and ES."""
    if not es_bars or len(es_bars) < 10:
        return None

    nq_recent = nq_bars[max(0, idx - 10):idx + 1]
    es_recent = es_bars[-10:]

    nq_low = min(b["low"] for b in nq_recent)
    nq_high = max(b["high"] for b in nq_recent)
    es_low = min(b["low"] for b in es_recent)
    es_high = max(b["high"] for b in es_recent)

    bar = nq_bars[idx]

    # Bullish: NQ makes lower low while ES doesn't
    if nq_low == bar["low"] and bar["low"] < nq_recent[-2]["low"] \
       and es_low >= es_recent[-2]["low"]:
        return "bullish"
    # Bearish: NQ makes higher high while ES doesn't
    if nq_high == bar["high"] and bar["high"] > nq_recent[-2]["high"] \
       and es_high <= es_recent[-2]["high"]:
        return "bearish"

    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    daily_bars = get_bars(data_dir, symbol, "D1")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")
    es_m1_bars = get_bars(data_dir, "ES", "M1")

    if not m1_bars or not m15_bars:
        print("No data found")
        return

    # ── Step 1: Daily bias ──────────────────────────────────────────
    if daily_bars and len(daily_bars) >= 3:
        d2 = daily_bars[-2]
        d1 = daily_bars[-1]
        if d2["close"] > d2["open"] and d1["close"] > d1["open"]:
            log.event(1, "Daily Bias: Bullish", d1["time"],
                      d1["close"], "D1")
        elif d2["close"] < d2["open"] and d1["close"] < d1["open"]:
            log.event(1, "Daily Bias: Bearish", d1["time"],
                      d1["close"], "D1")
        else:
            log.event(1, "Daily Bias: Neutral", d1["time"],
                      d1["close"], "D1")

    # ── Step 2: 15M FVG identification ──────────────────────────────
    m15_fvgs = detect_fvg(m15_bars)

    if m15_fvgs:
        log.event(2, "15M FVG Levels Identified",
                  m15_bars[-1]["time"], 0, "M15",
                  f"Count: {len(m15_fvgs)}")
    else:
        log.event(2, "No 15M FVG Found", m15_bars[-1]["time"],
                  0, "M15")

    # ── Step 3-4: 9:30-11:30 AM window ──────────────────────────────
    has_tapped_15m_fvg = False

    for i in range(5, len(m1_bars)):
        ny = get_ny_time(m1_bars[i]["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11 and ny.minute > 30:
            break

        bar = m1_bars[i]

        # ── Check if price taps 15M FVG (A+ setup) ──────────────
        if m15_fvgs and not has_tapped_15m_fvg:
            for fvg in m15_fvgs:
                if fvg["bottom"] <= bar["close"] <= fvg["top"]:
                    has_tapped_15m_fvg = True
                    log.event(3, "Price Tapped 15M FVG (A+ Setup)",
                              bar["time"], bar["close"], "M1",
                              f"FVG: {fvg['top']:.2f}-{fvg['bottom']:.2f}")
                    break

        # ── SMT divergence ──────────────────────────────────────
        smt_dir = check_smt_divergence(m1_bars, i, es_m1_bars)
        if smt_dir is None:
            continue

        log.event(4, f"SMT Divergence ({smt_dir.upper()})",
                  bar["time"], bar["close"], "M1",
                  "NQ vs ES confirmed")

        # ── 1M FVG inversion ────────────────────────────────────
        fvgs = detect_fvg(m1_bars[max(0, i - 8):i + 1])
        if not fvgs:
            continue

        entry_found = False
        for fvg in fvgs:
            if smt_dir == "bullish" and bar["close"] > fvg["top"]:
                log.event(5, "1M FVG Inversion (Long Entry)",
                          bar["time"], bar["close"], "M1",
                          f"FVG: {fvg['top']:.2f}-{fvg['bottom']:.2f}")

                setup_type = "A+" if has_tapped_15m_fvg else "A"
                sl = round(bar["low"] * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)

                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"setup_type": setup_type,
                           "smt_nq_es": "confirmed",
                           "tapped_15m_fvg": has_tapped_15m_fvg,
                           "management": "1st partial 1:1, 2nd partial 1:2, "
                                         "BE at closest pool"})
                entry_found = True
                break

            if smt_dir == "bearish" and bar["close"] < fvg["bottom"]:
                log.event(5, "1M FVG Inversion (Short Entry)",
                          bar["time"], bar["close"], "M1",
                          f"FVG: {fvg['top']:.2f}-{fvg['bottom']:.2f}")

                setup_type = "A+" if has_tapped_15m_fvg else "A"
                sl = round(bar["high"] * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)

                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"setup_type": setup_type,
                           "smt_nq_es": "confirmed",
                           "tapped_15m_fvg": has_tapped_15m_fvg,
                           "management": "1st partial 1:1, 2nd partial 1:2, "
                                         "BE at closest pool"})
                entry_found = True
                break

        if entry_found:
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
