"""
Strategy: Life Of A Day Trader Living in Bali
Source: Faiz SMC
Video: https://www.youtube.com/watch?v=MJRwsCzmB1s

Core Concept:
  D1 liquidity sweep context. Pre-9:30 15M swing levels.
  Post-9:30 multi-TF inversion (1M→3M). Highest TF FVG inversion entry.
  BE at nearest liquidity, 1:2 target.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "BaliDayTrader"
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

    # ── Step 1: D1 context ──────────────────────────────────────────
    d1_highs = []
    d1_lows = []
    for i in range(1, len(d1_bars) - 1):
        if d1_bars[i]["high"] > d1_bars[i - 1]["high"] and d1_bars[i]["high"] > d1_bars[i + 1]["high"]:
            d1_highs.append(d1_bars[i]["high"])
        if d1_bars[i]["low"] < d1_bars[i - 1]["low"] and d1_bars[i]["low"] < d1_bars[i + 1]["low"]:
            d1_lows.append(d1_bars[i]["low"])

    d1_swept_low = m1_bars and m1_bars[-1]["low"] < min(d1_lows) if d1_lows else False
    d1_swept_high = m1_bars and m1_bars[-1]["high"] > max(d1_highs) if d1_highs else False
    log.event(1, "D1 Context", d1_bars[-1]["time"], d1_bars[-1]["close"], "D1",
              f"External high swept={d1_swept_high}, low swept={d1_swept_low}")

    # ── Step 2: Pre-9:30 15M levels ─────────────────────────────────
    m15_pre930 = [b for b in m15_bars if get_ny_time(b["time"]).hour < 9 or
                  (get_ny_time(b["time"]).hour == 9 and get_ny_time(b["time"]).minute < 30)]
    if not m15_pre930:
        log.event(2, "No pre-9:30 bars", m15_bars[-1]["time"], 0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    sw_highs = []
    sw_lows = []
    for i in range(1, len(m15_pre930) - 1):
        if m15_pre930[i]["high"] > m15_pre930[i - 1]["high"] and m15_pre930[i]["high"] > m15_pre930[i + 1]["high"]:
            sw_highs.append(m15_pre930[i]["high"])
        if m15_pre930[i]["low"] < m15_pre930[i - 1]["low"] and m15_pre930[i]["low"] < m15_pre930[i + 1]["low"]:
            sw_lows.append(m15_pre930[i]["low"])

    log.event(2, "Pre-9:30 15M Swing Levels", m15_pre930[-1]["time"],
              m15_pre930[-1]["close"], "M15",
              f"Swings: {len(sw_highs)}H/{len(sw_lows)}L")

    # ── Step 3-4: Post-9:30 multi-TF inversion ──────────────────────
    m1_start = next(
        (i for i, b in enumerate(m1_bars)
         if get_ny_time(b["time"]).hour >= 9 and get_ny_time(b["time"]).minute >= 30), 0
    )

    state = "WAIT_ENTRY"
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
        for m in [3, 2, 1]:
            candles = seg if m == 1 else aggregate(seg, m)
            ifvgs = detect_ifvg(candles)
            for iv in ifvgs:
                if m > best_tf:
                    best_ifvg = iv
                    best_tf = m

        if not best_ifvg:
            continue

        if best_ifvg["direction"] == "bullish" and bar["close"] > best_ifvg["top"] and bar["close"] > bar["open"]:
            log.event(3, f"Bullish iFVG Entry (M{best_tf})",
                      bar["time"], bar["close"], f"M{best_tf}")
            sl = round(bar["low"] * 0.9998, 5)
            tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
            log.trade("LONG", bar["close"], sl, tp, bar["time"], symbol,
                      STRATEGY_NAME,
                      {"ifvg_tf": f"M{best_tf}", "ifvg_top": best_ifvg["top"],
                       "ifvg_bottom": best_ifvg["bottom"],
                       "management": "BE at nearest liquidity, 1:2 target"})
            trade_taken = True
            break
        elif best_ifvg["direction"] == "bearish" and bar["close"] < best_ifvg["bottom"] and bar["close"] < bar["open"]:
            log.event(3, f"Bearish iFVG Entry (M{best_tf})",
                      bar["time"], bar["close"], f"M{best_tf}")
            sl = round(bar["high"] * 1.0002, 5)
            tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
            log.trade("SHORT", bar["close"], sl, tp, bar["time"], symbol,
                      STRATEGY_NAME,
                      {"ifvg_tf": f"M{best_tf}", "ifvg_top": best_ifvg["top"],
                       "ifvg_bottom": best_ifvg["bottom"],
                       "management": "BE at nearest liquidity, 1:2 target"})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
