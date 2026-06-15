"""
Strategy: The 1-Candle Hourly Range Strategy
Source: Faiz SMC ("one candle is all you need..")
Video: https://www.youtube.com/watch?v=osc_hFXmQZA

Core Concept:
  1H candle: Gold 7AM, NQ 8AM. Sweep boundary → 2M CISD + range return.
  Entry at close or 50% retrace. Target opposite side. No 1M chart.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "OneCandleHourlyRange"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["H1", "M2"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m2_bars = get_bars(data_dir, symbol, "M2")

    if not h1_bars or not m2_bars:
        print("No data found")
        return

    # ── Step 1: Reference candle ────────────────────────────────────
    ref_hour = 7 if symbol.upper() in ("XAUUSD", "GC") else 8
    ref_high = 0.0
    ref_low = 0.0
    ref_time = None

    for b in h1_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == ref_hour and ny.minute == 0:
            ref_high = b["high"]
            ref_low = b["low"]
            ref_time = b["time"]
            log.event(1, f"Reference H1 Candle ({ref_hour}:00 NY)",
                      b["time"], ref_high, "H1",
                      f"High={ref_high:.2f}, Low={ref_low:.2f}")
            break

    if not ref_time:
        log.event(1, "Reference Candle Not Found", h1_bars[-1]["time"], 0, "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── State Machine on H1 (sweep) → M2 (entry) ────────────────────
    state = "WAIT_SWEEP"
    sweep_dir = None
    sweep_extreme = 0.0
    trade_taken = False
    ref_bar_idx = next(i for i, b in enumerate(h1_bars) if b["time"] == ref_time)

    for i in range(ref_bar_idx + 1, len(h1_bars)):
        h1_bar = h1_bars[i]
        ny = get_ny_time(h1_bar["time"])

        if trade_taken:
            break

        # ── Step 2: Sweep of H1 range boundary ───────────────────
        if state == "WAIT_SWEEP":
            if h1_bar["high"] > ref_high:
                sweep_dir = "bearish"
                sweep_extreme = h1_bar["high"]
                state = "WAIT_M2_CONFIRM"
                log.event(2, "H1 High Swept (Short Setup)", h1_bar["time"],
                          h1_bar["high"], "H1")
            elif h1_bar["low"] < ref_low:
                sweep_dir = "bullish"
                sweep_extreme = h1_bar["low"]
                state = "WAIT_M2_CONFIRM"
                log.event(2, "H1 Low Swept (Long Setup)", h1_bar["time"],
                          h1_bar["low"], "H1")

        # ── Step 3: M2 CISD + range return ───────────────────────
        if state == "WAIT_M2_CONFIRM":
            # Get M2 bars between prev H1 and this H1
            prev_h1_time = h1_bars[i - 1]["time"]
            m2_seg = [b for b in m2_bars
                      if b["time"] >= prev_h1_time and b["time"] <= h1_bar["time"]]

            if len(m2_seg) < 3:
                continue

            cisd_list = detect_cisd(m2_seg)
            valid_cisd = [s for s in cisd_list if s["direction"] == sweep_dir]

            if not valid_cisd:
                continue

            # Check range return
            inside = False
            if sweep_dir == "bearish":
                inside = any(b["close"] < ref_high for b in m2_seg[-4:])
            else:
                inside = any(b["close"] > ref_low for b in m2_seg[-4:])

            if not inside:
                continue

            log.event(3, f"CISD + Range Return ({sweep_dir.upper()})",
                      h1_bar["time"], h1_bar["close"], "M2",
                      "Entry conditions met.")

            # Entry at close or 50% retrace
            last_m2 = m2_seg[-1]
            fib_50 = (last_m2["high"] + last_m2["low"]) / 2
            entry = last_m2["close"]

            if sweep_dir == "bearish":
                sl = round(sweep_extreme * 1.0002, 2)
                tp = round(ref_low, 2)
                log.trade("SHORT", entry, sl, tp, last_m2["time"], symbol,
                          STRATEGY_NAME,
                          {"ref_high": ref_high, "ref_low": ref_low,
                           "sweep_extreme": sweep_extreme,
                           "entry_type": "close",
                           "alt_entry_50pct": round(fib_50, 2),
                           "cisd": True})
            else:
                sl = round(sweep_extreme * 0.9998, 2)
                tp = round(ref_high, 2)
                log.trade("LONG", entry, sl, tp, last_m2["time"], symbol,
                          STRATEGY_NAME,
                          {"ref_high": ref_high, "ref_low": ref_low,
                           "sweep_extreme": sweep_extreme,
                           "entry_type": "close",
                           "alt_entry_50pct": round(fib_50, 2),
                           "cisd": True})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
