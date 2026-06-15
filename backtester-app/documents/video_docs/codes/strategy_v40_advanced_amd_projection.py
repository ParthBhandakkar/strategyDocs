"""
Strategy: Advanced AMD & Precision Projection Model
Source: Faiz SMC ("I Simplified ICT PO3 Trading Strategy.. (High Winrate)")
Video: https://www.youtube.com/watch?v=CD041rzY67Y

Core Concept:
  D1 2-day bias → daily open → 15M fib -2.0/-2.5 manipulation zone.
  Sweep + CISD/MSS entry on 15M. TP = -2.0 from reversal swing.
  London/NY sessions only.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "AdvancedAMDProjection"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["D1", "M15"]


def two_day_bias(d1_bars):
    if len(d1_bars) < 3:
        return None
    d1 = d1_bars[-3]
    d2 = d1_bars[-2]
    d3 = d1_bars[-1]
    if d1["close"] > d1["open"] and d2["close"] > d2["open"] and d2["close"] > d1["high"]:
        return {"bias": "bullish", "d1": d1, "d2": d2, "d3": d3}
    if d1["close"] < d1["open"] and d2["close"] < d2["open"] and d2["close"] < d1["low"]:
        return {"bias": "bearish", "d1": d1, "d2": d2, "d3": d3}
    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    d1_bars = get_bars(data_dir, symbol, "D1")
    m15_bars = get_bars(data_dir, symbol, "M15")

    if not d1_bars or not m15_bars:
        print("No data found")
        return

    # ── Step 1: Daily bias ──────────────────────────────────────────
    bi = two_day_bias(d1_bars)
    if not bi:
        log.event(1, "No Daily Bias", d1_bars[-1]["time"],
                  d1_bars[-1]["close"], "D1", "Skip.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    bias = bi["bias"]
    d3 = bi["d3"]
    log.event(1, f"Daily Bias: {bias.upper()}", d3["time"], d3["open"], "D1",
              f"Day 2 close {'above d1 high' if bias=='bullish' else 'below d1 low'}.")

    today_open = d3["open"]
    today_date = get_ny_time(d3["time"]).date()

    m15_start = next(
        (i for i, b in enumerate(m15_bars)
         if get_ny_time(b["time"]).date() == today_date), None
    )
    if m15_start is None:
        log.event(2, "No 15M Data", d3["time"], today_open, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # Left-side swing for fib reference
    left_m15 = m15_bars[:m15_start]
    sw_highs = detect_swing_highs(left_m15) if left_m15 else []
    sw_lows = detect_swing_lows(left_m15) if left_m15 else []

    fib_high = sw_highs[-1]["price"] if sw_highs else None
    fib_low = sw_lows[-1]["price"] if sw_lows else None

    # Target pool: if bull, find nearest left-side low
    target_pool = None
    if bias == "bullish" and sw_lows:
        target_pool = sw_lows[-1]["price"]
    elif bias == "bearish" and sw_highs:
        target_pool = sw_highs[-1]["price"]

    log.event(2, f"Target {'Low' if bias=='bullish' else 'High'} Pool",
              m15_bars[m15_start]["time"] if m15_start < len(m15_bars) else "",
              target_pool or 0, "M15",
              f"Pool={target_pool:.2f}" if target_pool else "None")

    # ── State Machine ───────────────────────────────────────────────
    state = "WAIT_SWEEP"
    sweep_extreme = 0.0
    trade_taken = False

    for i in range(m15_start + 1, len(m15_bars)):
        bar = m15_bars[i]
        ny = get_ny_time(bar["time"])

        if ny.date() != today_date:
            break
        if ny.hour < 3 or (7 <= ny.hour < 12):
            pass  # London or NY session
        elif 3 <= ny.hour < 7:
            pass  # London
        elif ny.hour >= 12:
            break
        if trade_taken:
            break

        # ── Step 2: Sweep + fib zone ─────────────────────────────
        if state == "WAIT_SWEEP":
            if bias == "bullish" and target_pool and bar["low"] < target_pool:
                sweep_extreme = bar["low"]
                state = "WAIT_CONFIRM"
                log.event(3, "Low Swept + Fib Zone Check", bar["time"],
                          bar["low"], "M15",
                          f"Swept {target_pool:.2f}")
            elif bias == "bearish" and target_pool and bar["high"] > target_pool:
                sweep_extreme = bar["high"]
                state = "WAIT_CONFIRM"
                log.event(3, "High Swept + Fib Zone Check", bar["time"],
                          bar["high"], "M15",
                          f"Swept {target_pool:.2f}")

        # ── Step 3: Entry ─────────────────────────────────────────
        if state == "WAIT_CONFIRM":
            recent = m15_bars[max(0, i - 4):i + 1]
            mss = [s for s in detect_mss(recent) if s["direction"] == bias]
            cisd = [s for s in detect_cisd(recent) if s["direction"] == bias]

            if not (mss or cisd):
                continue

            trigger = "CISD" if cisd else "MSS"
            log.event(4, f"Entry ({trigger})", bar["time"], bar["close"],
                      "M15", "Entry triggered.")

            # TP: fib -2.0 from reversal swing or 1:2
            if bias == "bullish":
                sl = round(sweep_extreme * 0.9998, 2)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 2)
                log.trade("LONG", bar["close"], sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"daily_bias": bias, "today_open": today_open,
                           "target_pool": target_pool,
                           "sweep_price": sweep_extreme,
                           "trigger": trigger,
                           "fib_high": fib_high, "fib_low": fib_low})
            else:
                sl = round(sweep_extreme * 1.0002, 2)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 2)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"daily_bias": bias, "today_open": today_open,
                           "target_pool": target_pool,
                           "sweep_price": sweep_extreme,
                           "trigger": trigger,
                           "fib_high": fib_high, "fib_low": fib_low})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
