"""
Strategy: 1-Minute Scalping Live Trade (SMT + iFVG)
Source: Faiz SMC ("How I Made $2,130 In 3 Minutes Day Trading")
Video: https://www.youtube.com/watch?v=ksLTkMjm7-Y

Core Concept:
  D1/H1/5M story (liquidity sweeps, MSS, DOL). 1M execution after
  9:30 AM NY. Opposite liquidity sweep + SMT divergence (NQ/ES).
  iFVG entry trigger. 40% at 1:1, rest to DOL.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "LiveTradeSMTiFVG"
SYMBOL = "NQ"
TIMEFRAMES = ["D1", "H1", "M5", "M1"]


def check_smt(m1_nq: list, idx: int, m1_es: list):
    if not m1_es or len(m1_es) < 8:
        return None

    nq_seg = m1_nq[max(0, idx - 8):idx + 1]
    es_seg = m1_es[-8:]

    bar = m1_nq[idx]
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


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m1_bars = get_bars(data_dir, symbol, "M1")
    es_m1_bars = get_bars(data_dir, "ES", "M1")

    if not m1_bars:
        print("No data found")
        return

    # ── Story: find recent equal highs/lows on 5M ────────────────────
    m5_bars = get_bars(data_dir, symbol, "M5")
    dol_level = None
    bias = None

    if m5_bars and len(m5_bars) >= 10:
        recent = m5_bars[-10:]
        highs = [b["high"] for b in recent]
        lows = [b["low"] for b in recent]

        for i in range(len(highs)):
            for j in range(i + 1, len(highs)):
                if abs(highs[i] - highs[j]) / highs[i] < 0.001:
                    dol_level = highs[i]
                    bias = "bearish"
                if abs(lows[i] - lows[j]) / lows[i] < 0.001:
                    dol_level = lows[i]
                    bias = "bullish"

    if bias:
        log.event(1, f"Story: {bias.upper()}, DOL={dol_level}",
                  m5_bars[-1]["time"], dol_level or 0, "M5")

    # ── Execution: 1M after 9:30 AM ────────────────────────────────
    for i in range(5, len(m1_bars)):
        ny = get_ny_time(m1_bars[i]["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11 and ny.minute > 30:
            break

        bar = m1_bars[i]

        # ── Opposite sweep ──────────────────────────────────────
        lookback = max(0, i - 10)
        recent_high = max(b["high"] for b in m1_bars[lookback:i])
        recent_low = min(b["low"] for b in m1_bars[lookback:i])

        if bias == "bullish" and bar["low"] < recent_low:
            log.event(2, "Opposite Sweep (Low)", bar["time"],
                      bar["low"], "M1")
        elif bias == "bearish" and bar["high"] > recent_high:
            log.event(2, "Opposite Sweep (High)", bar["time"],
                      bar["high"], "M1")
        else:
            continue

        # ── SMT divergence ──────────────────────────────────────
        smt_dir = check_smt(m1_bars, i, es_m1_bars)
        if smt_dir is None:
            continue

        log.event(3, f"SMT Divergence ({smt_dir.upper()})",
                  bar["time"], bar["close"], "M1", "NQ/ES")

        # ── iFVG entry ─────────────────────────────────────────
        fvgs = detect_fvg(m1_bars[max(0, i - 8):i + 1])
        if not fvgs:
            continue

        for fvg in fvgs:
            if smt_dir == "bullish" and bar["close"] > fvg["top"]:
                log.event(4, "iFVG Entry (Long)", bar["time"],
                          bar["close"], "M1")

                sl = round(bar["low"] * 0.9998, 5)
                tp = round(dol_level, 5) if dol_level else \
                     round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"smt": "confirmed", "dol": dol_level,
                           "management": "40% at 1:1, rest to DOL"})
                break

            if smt_dir == "bearish" and bar["close"] < fvg["bottom"]:
                log.event(4, "iFVG Entry (Short)", bar["time"],
                          bar["close"], "M1")

                sl = round(bar["high"] * 1.0002, 5)
                tp = round(dol_level, 5) if dol_level else \
                     round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"smt": "confirmed", "dol": dol_level,
                           "management": "40% at 1:1, rest to DOL"})
                break
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
