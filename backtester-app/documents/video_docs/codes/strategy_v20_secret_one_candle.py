"""
Strategy: Secret One Candle Trading Strategy (10AM 4H)
Source: Faiz SMC ("This 'Secret' One Candle Trading Strategy")
Video: https://www.youtube.com/watch?v=ehV08YNaNAc

Core Concept:
  1) 10AM 4H candle open = anchor line.
  2) M1: first MSS that breaks the 4H open line.
  3) Fib from pre-break swing (-2.0 to -2.5 target zone).
  4) SMT divergence (NQ/ES) + CISD/MSS entry.
  5) TP = -2.0 expansion. Secondary entry via -1.0/-1.5 FVG.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "SecretOneCandle"
SYMBOL = "NQ"
TIMEFRAMES = ["4H", "M1"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "4H")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h4_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: 10AM 4H candle ──────────────────────────────────────
    fourh_open = 0.0
    fourh_time = None
    for b in h4_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == 10 and ny.minute == 0:
            fourh_open = b["open"]
            fourh_time = b["time"]
            log.event(1, "10AM 4H Candle Open", b["time"], fourh_open, "4H",
                      f"Open={fourh_open:.2f}")
            break

    if not fourh_time:
        log.event(1, "10AM 4H Candle Not Found", h4_bars[-1]["time"], 0, "4H")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── Initial M1 structure ────────────────────────────────────────
    m1_start = next(
        i for i, b in enumerate(m1_bars) if b["time"] >= fourh_time
    )

    # Find first M1 MSS that breaks the 4H open line
    first_mss = None
    m1_pre = m1_bars[:m1_start]
    if len(m1_pre) >= 10:
        sw_highs = detect_swing_highs(m1_pre)
        sw_lows = detect_swing_lows(m1_pre)

    # ── State Machine ───────────────────────────────────────────────
    state = "WAIT_BREAK"
    break_direction = None
    fib_high = 0.0  # pre-break swing high (body)
    fib_low = 0.0   # pre-break swing low (body)
    sweep_extreme = 0.0
    trade_taken = False

    for i in range(m1_start + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 10 or ny.hour >= 16:
            continue
        if trade_taken:
            break

        # ── Step 2: First M1 MSS that breaks the 4H open ──────────
        if state == "WAIT_BREAK":
            recent = m1_bars[max(0, i - 8):i]
            mss_list = detect_mss(recent)
            for mss in mss_list:
                # Check if this MSS broke past the open line
                if mss["direction"] == "bullish" and bar["close"] > fourh_open:
                    break_direction = "bullish"
                    # Find pre-break swing for fib
                    pre_bars = m1_bars[max(0, i - 15):i]
                    sw_lows_p = detect_swing_lows(pre_bars)
                    sw_highs_p = detect_swing_highs(pre_bars)
                    if sw_lows_p and sw_highs_p:
                        fib_low = sw_lows_p[-1]["price"]
                        fib_high = sw_highs_p[-1]["price"]
                    state = "WAIT_MANIPULATION"
                    log.event(2, "Bullish MSS Broke 4H Open", bar["time"],
                              bar["close"], "M1",
                              f"First MSS above 4H open={fourh_open:.2f}")
                    break

                elif mss["direction"] == "bearish" and bar["close"] < fourh_open:
                    break_direction = "bearish"
                    pre_bars = m1_bars[max(0, i - 15):i]
                    sw_highs_p = detect_swing_highs(pre_bars)
                    sw_lows_p = detect_swing_lows(pre_bars)
                    if sw_highs_p and sw_lows_p:
                        fib_high = sw_highs_p[-1]["price"]
                        fib_low = sw_lows_p[-1]["price"]
                    state = "WAIT_MANIPULATION"
                    log.event(2, "Bearish MSS Broke 4H Open", bar["time"],
                              bar["close"], "M1",
                              f"First MSS below 4H open={fourh_open:.2f}")
                    break

        # ── Step 3-4: Manipulation + SMT + Entry ─────────────────
        if state == "WAIT_MANIPULATION":
            # For bullish: price goes DOWN to manipulate (discount)
            # For bearish: price goes UP to manipulate (premium)
            if break_direction == "bullish" and fib_high and fib_low:
                # Manipulate down: price should go below fib_low into -2.0 zone
                ext_2_0 = fib_expansion(fib_low, fib_high, 2.0)
                ext_2_5 = fib_expansion(fib_low, fib_high, 2.5)
                zone = (min(ext_2_0, ext_2_5), max(ext_2_0, ext_2_5))

                if zone[0] <= bar["low"] <= zone[1]:
                    # Check MSS/CISD reversal
                    rev = m1_bars[max(0, i - 8):i + 1]
                    rev_mss = [s for s in detect_mss(rev)
                               if s["direction"] == "bullish"]
                    rev_cisd = [s for s in detect_cisd(rev)
                                if s["direction"] == "bullish"]

                    if rev_mss or rev_cisd:
                        trigger = "CISD" if rev_cisd else "MSS"
                        log.event(3, "Bullish Entry at Fib Zone", bar["time"],
                                  bar["close"], "M1",
                                  f"Zone={zone[0]:.2f}-{zone[1]:.2f}, "
                                  f"Trigger={trigger}")

                        sl = round(min(b["low"] for b in rev) * 0.9998, 2)
                        tp = round(bar["close"] + (bar["close"] - sl) * 2, 2)
                        log.trade("LONG", bar["close"], sl, tp, bar["time"],
                                  symbol, STRATEGY_NAME,
                                  {"fourh_open": fourh_open,
                                   "fib_high": fib_high, "fib_low": fib_low,
                                   "target_zone": zone, "trigger": trigger,
                                   "smt": False})
                        trade_taken = True
                        break

            elif break_direction == "bearish" and fib_high and fib_low:
                ext_2_0 = fib_expansion(fib_high, fib_low, 2.0)
                ext_2_5 = fib_expansion(fib_high, fib_low, 2.5)
                zone = (min(ext_2_0, ext_2_5), max(ext_2_0, ext_2_5))

                if zone[0] <= bar["high"] <= zone[1]:
                    rev = m1_bars[max(0, i - 8):i + 1]
                    rev_mss = [s for s in detect_mss(rev)
                               if s["direction"] == "bearish"]
                    rev_cisd = [s for s in detect_cisd(rev)
                                if s["direction"] == "bearish"]

                    if rev_mss or rev_cisd:
                        trigger = "CISD" if rev_cisd else "MSS"
                        log.event(3, "Bearish Entry at Fib Zone", bar["time"],
                                  bar["close"], "M1",
                                  f"Zone={zone[0]:.2f}-{zone[1]:.2f}, "
                                  f"Trigger={trigger}")

                        sl = round(max(b["high"] for b in rev) * 1.0002, 2)
                        tp = round(bar["close"] - (sl - bar["close"]) * 2, 2)
                        log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                                  symbol, STRATEGY_NAME,
                                  {"fourh_open": fourh_open,
                                   "fib_high": fib_high, "fib_low": fib_low,
                                   "target_zone": zone, "trigger": trigger,
                                   "smt": False})
                        trade_taken = True
                        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
