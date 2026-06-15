"""
Strategy: Stupid Simple Gold Trading Strategy (Asian Session)
Source: Faiz SMC ("Stupid Simple Gold Trading Strategy That Works Everyday!")
Video: https://www.youtube.com/watch?v=Yinhff6uLyw

Core Concept:
  Gold. 8PM-12AM NY (Asian open). 15M pre-open unswept high/low.
  Sweep + M1 MSS + close back inside range. Entry at breaker/FVG.
  TP 1:2. Invalid if both sides swept before entry.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "StupidSimpleGold"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M15", "M1"]


def find_unswept_swings(bars, upto_idx):
    """Find most recent unswept swing high and low in bars up to upto_idx."""
    sw_highs = []
    sw_lows = []
    for i in range(1, upto_idx - 1):
        c = bars[i]
        p = bars[i - 1]
        n = bars[i + 1]
        if i < upto_idx and c["high"] > p["high"] and c["high"] > n["high"]:
            sw_highs.append({"price": c["high"], "time": c["time"], "idx": i})
        if i < upto_idx and c["low"] < p["low"] and c["low"] < n["low"]:
            sw_lows.append({"price": c["low"], "time": c["time"], "idx": i})

    ref_high = sw_highs[-1] if sw_highs else None
    ref_low = sw_lows[-1] if sw_lows else None
    return ref_high, ref_low


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m15_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1-2: Find 8PM start and pre-open swings ────────────────
    eight_pm_idx = None
    for i, b in enumerate(m15_bars):
        ny = get_ny_time(b["time"])
        if ny.hour == 20 and ny.minute == 0:
            eight_pm_idx = i
            break

    if eight_pm_idx is None or eight_pm_idx < 5:
        log.event(1, "8PM Candle Not Found", m15_bars[-1]["time"], 0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    ref_high, ref_low = find_unswept_swings(m15_bars, eight_pm_idx)

    if not ref_high and not ref_low:
        log.event(1, "No Pre-Open Swings Found", m15_bars[eight_pm_idx]["time"],
                  0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, "Pre-Open Reference Levels",
              m15_bars[eight_pm_idx]["time"],
              ref_high["price"] if ref_high else ref_low["price"],
              "M15",
              f"High={ref_high['price']:.2f}" if ref_high else "No high"
              f" | Low={ref_low['price']:.2f}" if ref_low else "No low")

    # ── State Machine on M15 ────────────────────────────────────────
    state = "WAIT_SWEEP"
    sweep_direction = None
    sweep_idx = None
    trade_taken = False

    for i in range(eight_pm_idx + 1, len(m15_bars)):
        bar = m15_bars[i]
        ny = get_ny_time(bar["time"])

        # Only 8PM - 12AM NY
        if ny.hour < 20 and ny.hour >= 0:
            continue
        if ny.hour >= 0 and ny.minute >= 0 and ny.hour < 12:
            # After midnight, check if still before 12AM
            pass
        if ny.hour >= 0 and ny.hour < 12:
            pass
        if ny.hour >= 12 and ny.hour < 20:
            break

        if trade_taken:
            break

        # ── Step 3: Sweep reference H or L ─────────────────────────
        if state == "WAIT_SWEEP":
            if ref_high and bar["high"] > ref_high["price"]:
                sweep_direction = "bearish"
                sweep_idx = i
                state = "WAIT_M1_CONFIRM"
                log.event(2, "Reference High Swept", bar["time"],
                          bar["high"], "M15",
                          f"Swept ref high @ {ref_high['price']:.2f}")
            elif ref_low and bar["low"] < ref_low["price"]:
                sweep_direction = "bullish"
                sweep_idx = i
                state = "WAIT_M1_CONFIRM"
                log.event(2, "Reference Low Swept", bar["time"],
                          bar["low"], "M15",
                          f"Swept ref low @ {ref_low['price']:.2f}")

        # ── Step 4: M1 MSS + close inside range ──────────────────
        # Note: This is checked on M15 bar level as proxy for M1;
        # real implementation would scan M1 between M15 bars
        if state == "WAIT_M1_CONFIRM":
            # Find corresponding M1 bars
            m15_bar_time = bar["time"]
            m1_seg = [b for b in m1_bars
                      if b["time"] >= m15_bars[sweep_idx - 1]["time"]
                      and b["time"] <= m15_bar_time]

            if len(m1_seg) < 3:
                continue

            mss_list = detect_mss(m1_seg)
            valid_mss = [s for s in mss_list if s["direction"] == sweep_direction]

            if not valid_mss:
                continue

            # Check close back inside 15M range
            inside = False
            if sweep_direction == "bearish":
                inside = any(b["close"] < ref_high["price"] for b in m1_seg[-4:])
            else:
                inside = any(b["close"] > ref_low["price"] for b in m1_seg[-4:])

            if not inside:
                log.event(3, "MSS but no range return → skip", bar["time"],
                          bar["close"], "M15")
                state = "WAIT_SWEEP"
                continue

            log.event(3, f"MSS + Range Return ({sweep_direction.upper()})",
                      bar["time"], bar["close"], "M1",
                      "Conditions met for entry.")

            # Step 5: Find breaker or FVG
            fvgs = detect_fvg(m1_seg)
            valid_fvgs = [f for f in fvgs if f["direction"] == sweep_direction]

            entry = bar["close"]
            detail = "market"
            if valid_fvgs:
                entry = (valid_fvgs[-1]["top"] + valid_fvgs[-1]["bottom"]) / 2
                detail = "FVG limit"

            if sweep_direction == "bearish":
                sl = round(ref_high["price"] * 1.0002, 2)
                tp = round(entry - (sl - entry) * 2, 2)
                log.trade("SHORT", entry, sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"ref_high": ref_high["price"],
                           "ref_low": ref_low["price"] if ref_low else None,
                           "entry_type": detail,
                           "mss": True, "range_return": True})
            else:
                sl = round(ref_low["price"] * 0.9998, 2)
                tp = round(entry + (entry - sl) * 2, 2)
                log.trade("LONG", entry, sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"ref_high": ref_high["price"] if ref_high else None,
                           "ref_low": ref_low["price"],
                           "entry_type": detail,
                           "mss": True, "range_return": True})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
