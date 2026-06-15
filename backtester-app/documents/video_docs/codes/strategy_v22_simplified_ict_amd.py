"""
Strategy: Simplified ICT AMD Trading Strategy
Source: Faiz SMC ("I Simplified ICT AMD Trading Strategy..")
Video: https://www.youtube.com/watch?v=nV9gknhy2Ew

Core Concept:
  10AM 4H candle AMD on 1M (or 5M). Fib -2.0 to -2.5 manipulation zone.
  Price must exceed -2.0. SMT divergence + CISD entry.
  Target: -2.0/-2.5 expansion from reversal swing.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "SimplifiedICTAMD"
SYMBOL = "NQ"
TIMEFRAMES = ["4H", "M1", "M5"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "4H")
    m1_bars = get_bars(data_dir, symbol, "M1")
    m5_bars = get_bars(data_dir, symbol, "M5")

    if not h4_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: 10AM 4H candle ──────────────────────────────────────
    candle_open = 0.0
    candle_time = None
    for b in h4_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == 10 and ny.minute == 0:
            candle_open = b["open"]
            candle_time = b["time"]
            log.event(1, "10AM 4H Candle Open", b["time"], candle_open, "4H",
                      f"Open={candle_open:.2f}")
            break

    if not candle_time:
        log.event(1, "10AM Candle Not Found", h4_bars[-1]["time"], 0, "4H")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── State Machine ───────────────────────────────────────────────
    state = "WAIT_MANIPULATION"
    manip_direction = None
    fib_start = 0.0
    fib_end = 0.0
    sweep_extreme = 0.0
    trade_taken = False
    use_m5 = False

    m1_start = next(
        i for i, b in enumerate(m1_bars) if b["time"] >= candle_time
    )

    # Use M5 if choosing to
    m5_start = 0
    if m5_bars:
        m5_start = next(
            (i for i, b in enumerate(m5_bars) if b["time"] >= candle_time), 0
        )

    for i in range(m1_start + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 10 or ny.hour >= 16:
            continue
        if trade_taken:
            break

        # ── Step 3: Initial manipulation phase ─────────────────────
        if state == "WAIT_MANIPULATION":
            # Detect which way the manipulation goes (above or below open)
            seg = m1_bars[m1_start:i + 1]
            seg_high = max(b["high"] for b in seg)
            seg_low = min(b["low"] for b in seg)

            if seg_high - candle_open >= candle_open - seg_low:
                # Manipulating upward (bearish premium)
                manip_direction = "bearish"
                sweep_extreme = seg_high
                fib_start = candle_open
                # Use recent pre-open low as fib_end
                pre_lows = [b["low"] for b in m1_bars[max(0, m1_start - 20):m1_start]]
                fib_end = min(pre_lows) if pre_lows else candle_open
            else:
                manip_direction = "bullish"
                sweep_extreme = seg_low
                fib_start = candle_open
                pre_highs = [b["high"] for b in m1_bars[max(0, m1_start - 20):m1_start]]
                fib_end = max(pre_highs) if pre_highs else candle_open

            # Check if price exceeded -2.0
            if manip_direction == "bearish":
                ext_2_0 = fib_expansion(fib_start, fib_end, 2.0)
                if bar["high"] >= ext_2_0:
                    state = "WAIT_REVERSAL"
                    log.event(2, "Bearish Manipulation Past -2.0", bar["time"],
                              bar["high"], "M1",
                              f"Exceeded -2.0 target={ext_2_0:.2f}")
            else:
                ext_2_0 = fib_expansion(fib_end, fib_start, 2.0)
                if bar["low"] <= ext_2_0:
                    state = "WAIT_REVERSAL"
                    log.event(2, "Bullish Manipulation Past -2.0", bar["time"],
                              bar["low"], "M1",
                              f"Exceeded -2.0 target={ext_2_0:.2f}")

        # ── Step 4-5: SMT + CISD entry ─────────────────────────────
        if state == "WAIT_REVERSAL":
            recent = m1_bars[max(0, i - 8):i + 1]
            cisd = [s for s in detect_cisd(recent)
                    if s["direction"] == manip_direction]

            if not cisd:
                continue

            log.event(3, "CISD Confirmed", bar["time"], bar["close"], "M1",
                      f"Entry triggered.")

            # Target: fib expansion of reversal swing
            rev_low = min(b["low"] for b in recent)
            rev_high = max(b["high"] for b in recent)

            if manip_direction == "bearish":
                sl = round(sweep_extreme * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"fourh_open": candle_open,
                           "manip_direction": manip_direction,
                           "sweep_extreme": sweep_extreme,
                           "cisd": True, "smt": False,
                           "rev_high": rev_high, "rev_low": rev_low})
            else:
                sl = round(sweep_extreme * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"fourh_open": candle_open,
                           "manip_direction": manip_direction,
                           "sweep_extreme": sweep_extreme,
                           "cisd": True, "smt": False,
                           "rev_high": rev_high, "rev_low": rev_low})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
