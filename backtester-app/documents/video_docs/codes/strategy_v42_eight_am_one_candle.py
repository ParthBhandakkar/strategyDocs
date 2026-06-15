"""
Strategy: The 8 AM One-Candle Trading Strategy
Source: Faiz SMC ("This One Candle Can Change Your Life.. (Stupid Simple Strategy)")
Video: https://www.youtube.com/watch?v=YKbkZ4eRd04

Core Concept:
  8AM H1 range. Sweep after 9:30 AM. M1 MSS + close inside range.
  Entry at breaker/FVG. Partial 40-50% at 1:2 RR, BE, runner to opposite side.
  NQ only.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "EightAMOneCandle"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "M1"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h1_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: 8AM candle range ────────────────────────────────────
    range_high = 0.0
    range_low = 0.0
    found = False

    for b in h1_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == 8 and ny.minute == 0:
            range_high = b["high"]
            range_low = b["low"]
            log.event(1, "8AM H1 Range", b["time"], range_high, "H1",
                      f"High={range_high:.2f}, Low={range_low:.2f}")
            found = True
            break

    if not found:
        log.event(1, "8AM Candle Not Found", h1_bars[-1]["time"], 0, "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── State Machine (after 9:30 AM) ───────────────────────────────
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

        # ── Step 2-3: Sweep + M1 MSS + close inside ──────────────
        if state == "WAIT_SWEEP":
            if bar["high"] > range_high:
                sweep_dir = "bearish"
                sweep_extreme = bar["high"]
                state = "WAIT_MSS"
                log.event(2, "Range High Swept", bar["time"], bar["high"], "M1")
            elif bar["low"] < range_low:
                sweep_dir = "bullish"
                sweep_extreme = bar["low"]
                state = "WAIT_MSS"
                log.event(2, "Range Low Swept", bar["time"], bar["low"], "M1")

        if state == "WAIT_MSS":
            recent = m1_bars[max(0, i - 8):i + 1]
            valid_mss = [s for s in detect_mss(recent) if s["direction"] == sweep_dir]
            if not valid_mss:
                continue

            # Close inside range
            inside = (sweep_dir == "bearish" and bar["close"] < range_high) or \
                     (sweep_dir == "bullish" and bar["close"] > range_low)
            if not inside:
                continue

            state = "WAIT_ENTRY"
            log.event(3, f"MSS + Close Inside Range", bar["time"],
                      bar["close"], "M1")

        # ── Step 4-6: Entry + partial at 1:2 ────────────────────
        if state == "WAIT_ENTRY":
            recent = m1_bars[max(0, i - 6):i + 1]
            fvgs = [f for f in detect_fvg(recent) if f["direction"] == sweep_dir]
            entry = bar["close"]
            if fvgs:
                entry = (fvgs[-1]["top"] + fvgs[-1]["bottom"]) / 2

            if sweep_dir == "bearish":
                sl = round(sweep_extreme * 1.0002, 5)
                tp = round(range_low, 5)
                partial = round(entry - (sl - entry) * 2, 5)
                log.trade("SHORT", entry, sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"range_high": range_high, "range_low": range_low,
                           "sweep_extreme": sweep_extreme,
                           "partial_at_1_2": partial,
                           "management": "40-50% partial at 1:2, then BE"})
            else:
                sl = round(sweep_extreme * 0.9998, 5)
                tp = round(range_high, 5)
                partial = round(entry + (entry - sl) * 2, 5)
                log.trade("LONG", entry, sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"range_high": range_high, "range_low": range_low,
                           "sweep_extreme": sweep_extreme,
                           "partial_at_1_2": partial,
                           "management": "40-50% partial at 1:2, then BE"})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
