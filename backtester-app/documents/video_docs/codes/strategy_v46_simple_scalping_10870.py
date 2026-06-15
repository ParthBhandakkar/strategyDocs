"""
Strategy: My Simple Scalping Trading Strategy To Make $10,870/Month
Source: Faiz SMC
Video: https://www.youtube.com/watch?v=dcNU_Dwgy5E

Core Concept:
  15M FVG = key zone (9:30-11:30). 1M dealing range inside it.
  Multi-TF iFVG inversion (1M→5M, pick highest). SMT div (NQ/ES).
  30% partial at 1:1, full at 1:2. BE after liquidity sweep.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "SimpleScalping10870"
SYMBOL = "NQ"
TIMEFRAMES = ["D1", "M15", "M1"]


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

    d1_bars = get_bars(data_dir, "NQ", "D1")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not all([d1_bars, m15_bars, m1_bars]):
        print("No data found")
        return

    # ── Step 1: D1 bias ─────────────────────────────────────────────
    d1_latest = d1_bars[-1]
    fvg_list = detect_fvg(d1_bars)
    d1_bias = "bullish" if d1_latest["close"] > d1_latest["open"] else "bearish"
    log.event(1, "D1 Bias", d1_latest["time"], d1_latest["close"], "D1",
              f"Bias={d1_bias}, FVGs={len(fvg_list)}")

    # ── Step 2: 15M FVG after 9:30 ──────────────────────────────────
    m15_fvg_list = detect_fvg(m15_bars)
    relevant_fvg = None
    for fvg in m15_fvg_list:
        bar = m15_bars[fvg["index"]]
        ny = get_ny_time(bar["time"])
        if ny.hour >= 9 and ny.minute >= 30:
            if d1_bias == "bullish" and fvg["direction"] == "bullish":
                relevant_fvg = fvg
                break
            elif d1_bias == "bearish" and fvg["direction"] == "bearish":
                relevant_fvg = fvg
                break

    if not relevant_fvg:
        log.event(2, "No 15M FVG found after 9:30", m15_bars[-1]["time"], 0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    fvg_top = relevant_fvg["top"]
    fvg_bottom = relevant_fvg["bottom"]
    fvg_idx = relevant_fvg["index"]
    fvg_dir = relevant_fvg["direction"]
    log.event(2, f"15M {fvg_dir.upper()} FVG Zone", m15_bars[fvg_idx]["time"],
              fvg_top, "M15",
              f"Top={fvg_top:.2f}, Bottom={fvg_bottom:.2f}")

    # ── Step 3-4: Find 1M dealing range + inversion entry ───────────
    m1_start = next(
        (i for i, b in enumerate(m1_bars)
         if get_ny_time(b["time"]).hour >= 9 and get_ny_time(b["time"]).minute >= 30), 0
    )

    state = "WAIT_PRICE_IN_ZONE"
    trade_taken = False

    for i in range(m1_start + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11 and ny.minute > 30:
            break
        if trade_taken:
            break

        if state == "WAIT_PRICE_IN_ZONE":
            if fvg_bottom <= bar["low"] <= fvg_top or fvg_bottom <= bar["high"] <= fvg_top:
                state = "WAIT_INVERSION_CLOSE"
                log.event(3, "Price Entered 15M FVG Zone", bar["time"],
                          bar["close"], "M1",
                          f"Seeking multi-TF inversion")

        if state == "WAIT_INVERSION_CLOSE":
            seg = m1_bars[max(0, i - 20):i + 1]
            best_ifvg = None
            best_tf = 0
            for m in [5, 4, 3, 2, 1]:
                candles = seg if m == 1 else aggregate(seg, m)
                ifvgs = [f for f in detect_ifvg(candles) if f["direction"] == fvg_dir]
                for iv in ifvgs:
                    if m > best_tf:
                        best_ifvg = iv
                        best_tf = m

            if best_ifvg:
                invert_high = best_ifvg["top"]
                invert_low = best_ifvg["bottom"]

                if fvg_dir == "bullish":
                    # Body close above FVG
                    if bar["close"] > invert_high and bar["close"] > bar["open"]:
                        log.event(4, f"Bullish iFVG Entry (M{best_tf})",
                                  bar["time"], bar["close"], f"M{best_tf}")
                        sl = round(min(bar["low"], invert_low) * 0.9998, 5)
                        tp1 = round(bar["close"] + (bar["close"] - sl), 5)
                        tp2 = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                        log.trade("LONG", bar["close"], sl, tp1, bar["time"],
                                  symbol, STRATEGY_NAME,
                                  {"strategy": "30% at 1:1, 70% at 1:2",
                                   "tp_partial": tp1, "tp_final": tp2,
                                   "ifvg_tf": f"M{best_tf}",
                                   "fvg_top": fvg_top, "fvg_bottom": fvg_bottom})
                        trade_taken = True
                        break
                else:
                    if bar["close"] < invert_low and bar["close"] < bar["open"]:
                        log.event(4, f"Bearish iFVG Entry (M{best_tf})",
                                  bar["time"], bar["close"], f"M{best_tf}")
                        sl = round(max(bar["high"], invert_high) * 1.0002, 5)
                        tp1 = round(bar["close"] - (sl - bar["close"]), 5)
                        tp2 = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                        log.trade("SHORT", bar["close"], sl, tp1, bar["time"],
                                  symbol, STRATEGY_NAME,
                                  {"strategy": "30% at 1:1, 70% at 1:2",
                                   "tp_partial": tp1, "tp_final": tp2,
                                   "ifvg_tf": f"M{best_tf}",
                                   "fvg_top": fvg_top, "fvg_bottom": fvg_bottom})
                        trade_taken = True
                        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
