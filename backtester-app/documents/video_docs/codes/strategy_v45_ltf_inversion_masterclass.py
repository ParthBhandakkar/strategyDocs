"""
Strategy: Lower-Timeframe Inversion Masterclass
Source: Faiz SMC ("STOP Using ICT & Trade With This Strategy Instead.. (Stupid Simple)")
Video: https://www.youtube.com/watch?v=YKbkZ4eRd04

Core Concept:
  8AM H1 range (NQ). Sweep after 9:30 AM. Multi-TF iFVG (5M→1M, pick highest).
  Enter at inversion candle close. SL past sweep. TP = range opposite or 1:2.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "LTFInversionMasterclass"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "M5", "M1"]


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

    h1_bars = get_bars(data_dir, symbol, "H1")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h1_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1-2: 8AM H1 range ──────────────────────────────────────
    range_high = 0.0
    range_low = 0.0
    for b in h1_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == 8 and ny.minute == 0:
            range_high = b["high"]
            range_low = b["low"]
            break

    if not range_high:
        log.event(0, "8AM Candle Not Found", h1_bars[-1]["time"], 0, "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, "8AM H1 Range + DOL Context", h1_bars[0]["time"],
              range_high, "H1",
              f"High={range_high:.2f}, Low={range_low:.2f}")

    # ── State Machine (after 9:30) ──────────────────────────────────
    m1_start = next(
        (i for i, b in enumerate(m1_bars)
         if get_ny_time(b["time"]).hour >= 9 and get_ny_time(b["time"]).minute >= 30), 0
    )

    state = "WAIT_SWEEP"
    sweep_dir = None
    sweep_extreme = 0.0
    trade_taken = False

    for i in range(m1_start + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11:
            break
        if trade_taken:
            break

        if state == "WAIT_SWEEP":
            if bar["high"] > range_high:
                sweep_dir = "bearish"
                sweep_extreme = bar["high"]
                state = "WAIT_INVERSION"
                log.event(2, "Range High Swept", bar["time"], bar["high"], "M1")
            elif bar["low"] < range_low:
                sweep_dir = "bullish"
                sweep_extreme = bar["low"]
                state = "WAIT_INVERSION"
                log.event(2, "Range Low Swept", bar["time"], bar["low"], "M1")

        if state == "WAIT_INVERSION":
            seg = m1_bars[max(0, i - 10):i + 1]
            best_ifvg = None
            best_tf = 0
            for m in [5, 4, 3, 2, 1]:
                candles = seg if m == 1 else aggregate(seg, m)
                ifvgs = [f for f in detect_ifvg(candles) if f["direction"] == sweep_dir]
                for iv in ifvgs:
                    if m > best_tf:
                        best_ifvg = iv
                        best_tf = m

            if not best_ifvg:
                continue

            log.event(3, f"iFVG Entry (M{best_tf})", bar["time"],
                      bar["close"], f"M{best_tf}",
                      f"Entry triggered at inversion close.")

            if sweep_dir == "bearish":
                sl = round(sweep_extreme * 1.0002, 5)
                tp = round(range_low, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"range_high": range_high, "range_low": range_low,
                           "sweep_extreme": sweep_extreme,
                           "ifvg_tf": f"M{best_tf}"})
            else:
                sl = round(sweep_extreme * 0.9998, 5)
                tp = round(range_high, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"range_high": range_high, "range_low": range_low,
                           "sweep_extreme": sweep_extreme,
                           "ifvg_tf": f"M{best_tf}"})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
