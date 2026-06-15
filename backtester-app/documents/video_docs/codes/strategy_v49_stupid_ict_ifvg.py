"""
Strategy: Stupid ICT IFVG Trading Strategy That Works
Source: Faiz SMC
Video: https://www.youtube.com/watch?v=G5nhJEC59k4

Core Concept:
  D1/4H bias + SMT (NQ/ES). 15M level/FVG.
  Multi-TF iFVG inversion (1M→5M). 9:30-11:30 NY.
  1:1 or 0.7 partial, 1:1.5/1:2 full TP.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "StupidICTIFVG"
SYMBOL = "NQ"
TIMEFRAMES = ["H4", "M15", "M1"]


def aggregate(m1_bars, m):
    result = []
    for j in range(0, len(m1_bars), m):
        chunk = m1_bars[j:j + m]
        if not chunk:
            continue
        result.append({
            "time": chunk[0]["time"],
            "open": chunk[0]["open"],
            "high": max(b["high"] for b in chunk),
            "low": min(b["low"] for b in chunk),
            "close": chunk[-1]["close"],
        })
    return result


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, "NQ", "H4")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")
    es_m1 = get_bars(data_dir, "ES", "M1")

    if not all([h4_bars, m15_bars, m1_bars]):
        print("No data found")
        return

    # ── Step 1: D1/4H bias + SMT ────────────────────────────────────
    h4_highs = []
    h4_lows = []
    for i in range(1, len(h4_bars) - 1):
        if h4_bars[i]["high"] > h4_bars[i - 1]["high"] and h4_bars[i]["high"] > h4_bars[i + 1]["high"]:
            h4_highs.append((h4_bars[i]["time"], h4_bars[i]["high"]))
        if h4_bars[i]["low"] < h4_bars[i - 1]["low"] and h4_bars[i]["low"] < h4_bars[i + 1]["low"]:
            h4_lows.append((h4_bars[i]["time"], h4_bars[i]["low"]))

    bias = "bullish" if h4_bars[-1]["close"] > h4_bars[-1]["open"] else "bearish"

    # SMT check (NQ vs ES)
    smt_div = None
    if es_m1 and len(es_m1) > 5:
        nq_new_low = m1_bars[-1]["low"] < min(b["low"] for b in m1_bars[-20:])
        es_new_low = es_m1[-1]["low"] < min(b["low"] for b in es_m1[-20:])
        if nq_new_low and not es_new_low:
            smt_div = "bullish"
        nq_new_high = m1_bars[-1]["high"] > max(b["high"] for b in m1_bars[-20:])
        es_new_high = es_m1[-1]["high"] > max(b["high"] for b in es_m1[-20:])
        if nq_new_high and not es_new_high:
            smt_div = "bearish"

    log.event(1, "H4 Bias + SMT", h4_bars[-1]["time"],
              h4_bars[-1]["close"], "H4",
              f"Bias={bias}, SMT={smt_div or 'none'}")

    # ── Step 2: 15M level/FVG ───────────────────────────────────────
    m15_fvgs = detect_fvg(m15_bars)

    log.event(2, "15M Levels & FVGs", m15_bars[-1]["time"],
              m15_bars[-1]["close"], "M15",
              f"FVGs: {len(m15_fvgs)}")

    if not m15_fvgs:
        log.event(3, "No 15M FVG found", m15_bars[-1]["time"], 0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── Step 2-3: Post-9:30 multi-TF iFVG ───────────────────────────
    m1_start = next(
        (i for i, b in enumerate(m1_bars)
         if get_ny_time(b["time"]).hour >= 9 and get_ny_time(b["time"]).minute >= 30), 0
    )

    trade_taken = False

    for i in range(m1_start + 5, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11 and ny.minute > 30:
            break
        if trade_taken:
            break

        seg = m1_bars[max(0, i - 20):i + 1]
        best_ifvg = None
        best_tf = 0
        for m in [5, 4, 3, 2, 1]:
            candles = seg if m == 1 else aggregate(seg, m)
            ifvgs = [f for f in detect_ifvg(candles) if f["direction"] == bias]
            for iv in ifvgs:
                if m > best_tf:
                    best_ifvg = iv
                    best_tf = m

        if not best_ifvg:
            continue

        if best_ifvg["direction"] == "bullish" and bar["close"] > best_ifvg["top"] and bar["close"] > bar["open"]:
            log.event(4, f"Bullish iFVG Entry (M{best_tf})",
                      bar["time"], bar["close"], f"M{best_tf}",
                      f"SMT={smt_div or 'none'}")
            sl = round(bar["low"] * 0.9998, 5)
            tp = round(bar["close"] + (bar["close"] - sl) * 1.5, 5)
            log.trade("LONG", bar["close"], sl, tp, bar["time"], symbol,
                      STRATEGY_NAME,
                      {"ifvg_tf": f"M{best_tf}", "smt_divergence": smt_div or "none",
                       "management": "0.7/1:1 partial, 1:1.5/1:2 full TP"})
            trade_taken = True
            break
        elif best_ifvg["direction"] == "bearish" and bar["close"] < best_ifvg["bottom"] and bar["close"] < bar["open"]:
            log.event(4, f"Bearish iFVG Entry (M{best_tf})",
                      bar["time"], bar["close"], f"M{best_tf}",
                      f"SMT={smt_div or 'none'}")
            sl = round(bar["high"] * 1.0002, 5)
            tp = round(bar["close"] - (sl - bar["close"]) * 1.5, 5)
            log.trade("SHORT", bar["close"], sl, tp, bar["time"], symbol,
                      STRATEGY_NAME,
                      {"ifvg_tf": f"M{best_tf}", "smt_divergence": smt_div or "none",
                       "management": "0.7/1:1 partial, 1:1.5/1:2 full TP"})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
