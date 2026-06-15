"""
Strategy: One Trading Setup For Life - ICT 10AM PO3
Source: Faiz SMC ("One Trading Setup For Life - ICT 10AM PO3")
Video: https://www.youtube.com/watch?v=kz2rw7VWpMM

Core Concept:
  1) Bias from 4H 2AM vs 6AM candle close relationship.
  2) 10AM 4H open. 15M/5M FVG below (long) or above (short) open.
  3) Fib -2.0/-2.5 where manipulation taps the FVG.
  4) M1 MSS or iFVG entry on tap. TP 1:2.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "OneSetupForLife10AM"
SYMBOL = "NQ"
TIMEFRAMES = ["4H", "15M", "5M", "M1"]


def determine_bias(h4_bars):
    """Determine bias from 2AM vs 6AM 4H candle."""
    candle_2am = None
    candle_6am = None
    for b in h4_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == 2 and ny.minute == 0:
            candle_2am = b
        if ny.hour == 6 and ny.minute == 0:
            candle_6am = b
        if candle_2am and candle_6am:
            break
    if not candle_2am or not candle_6am:
        return None

    log_msg = f"2AM high={candle_2am['high']:.2f}, low={candle_2am['low']:.2f} | " \
              f"6AM high={candle_6am['high']:.2f}, low={candle_6am['low']:.2f}, " \
              f"close={candle_6am['close']:.2f}"

    # Bullish: 6AM closes above 2AM high
    if candle_6am["close"] > candle_2am["high"]:
        return "bullish", log_msg
    # Bearish: 6AM closes below 2AM low
    if candle_6am["close"] < candle_2am["low"]:
        return "bearish", log_msg
    # Rejection: wick above 2AM high but close back inside → bearish
    if candle_6am["high"] > candle_2am["high"] and candle_6am["close"] < candle_2am["high"]:
        return "bearish", log_msg + " | Rejection flip to bearish"
    # Rejection: wick below 2AM low but close back above → bullish
    if candle_6am["low"] < candle_2am["low"] and candle_6am["close"] > candle_2am["low"]:
        return "bullish", log_msg + " | Rejection flip to bullish"
    # No-trade: wicked both sides
    if candle_6am["high"] > candle_2am["high"] and candle_6am["low"] < candle_2am["low"]:
        return "no_trade", log_msg + " | No-trade: wicked both sides"
    return None, log_msg


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "4H")
    m15_bars = get_bars(data_dir, symbol, "15M")
    m5_bars = get_bars(data_dir, symbol, "5M")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h4_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: Daily bias from 2AM/6AM ─────────────────────────────
    bias, bias_log = determine_bias(h4_bars) or (None, "")
    if bias is None or bias == "no_trade":
        log.event(1, "Daily Bias: No Trade", h4_bars[-1]["time"],
                  h4_bars[-1]["close"], "4H",
                  bias_log or "Could not determine bias")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"Daily Bias: {bias.upper()}", h4_bars[-1]["time"],
              h4_bars[-1]["close"], "4H", bias_log)

    # ── Step 2: 10AM 4H candle open ─────────────────────────────────
    candle_open = 0.0
    candle_time = None
    for b in h4_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == 10 and ny.minute == 0:
            candle_open = b["open"]
            candle_time = b["time"]
            log.event(2, "10AM 4H Candle Open", b["time"], candle_open, "4H",
                      f"Open={candle_open:.2f}")
            break

    if not candle_time:
        log.event(2, "10AM Candle Not Found", h4_bars[-1]["time"], 0, "4H")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── Step 3: 15M/5M FVG on correct side of open ──────────────────
    m15_left = [b for b in m15_bars if b["time"] < candle_time] if m15_bars else []
    m15_fvgs = detect_fvg(m15_left) if m15_left else []

    target_fvg = None
    for f in m15_fvgs:
        if bias == "bullish" and f["direction"] == "bullish" and f["top"] < candle_open:
            target_fvg = f
            break
        if bias == "bearish" and f["direction"] == "bearish" and f["bottom"] > candle_open:
            target_fvg = f
            break

    if not target_fvg:
        # Fallback to 5M
        m5_left = [b for b in m5_bars if b["time"] < candle_time] if m5_bars else []
        m5_fvgs = detect_fvg(m5_left) if m5_left else []
        for f in m5_fvgs:
            if bias == "bullish" and f["direction"] == "bullish" and f["top"] < candle_open:
                target_fvg = f
                break
            if bias == "bearish" and f["direction"] == "bearish" and f["bottom"] > candle_open:
                target_fvg = f
                break

    if not target_fvg:
        log.event(3, "No Valid FVG on Correct Side of Open",
                  candle_time, candle_open, "15M/5M",
                  f"No {'bullish below' if bias == 'bullish' else 'bearish above'} FVG found.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(3, f"Target FVG ({'15M' if target_fvg in (m15_fvgs if m15_fvgs else []) else '5M'})",
              target_fvg["time"], target_fvg.get("avg", 0),
              "15M" if target_fvg in (m15_fvgs if m15_fvgs else []) else "5M",
              f"Top={target_fvg['top']:.2f}, Bottom={target_fvg['bottom']:.2f}")

    # ── State Machine ───────────────────────────────────────────────
    state = "WAIT_MANIPULATION"
    manip_extreme = 0.0
    fib_high = 0.0
    fib_low = 0.0
    trade_taken = False

    m1_start = next(
        i for i, b in enumerate(m1_bars) if b["time"] >= candle_time
    )

    for i in range(m1_start + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 10 or ny.hour >= 14:
            continue
        if trade_taken:
            break

        # ── Step 4: Manipulation into the FVG ────────────────────
        if state == "WAIT_MANIPULATION":
            # Check if price entered the target FVG area
            in_fvg = target_fvg["bottom"] <= bar["close"] <= target_fvg["top"]
            if not in_fvg:
                continue

            # Check direction relative to open
            if bias == "bullish" and bar["close"] < candle_open:
                manip_extreme = min(b["low"] for b in m1_bars[m1_start:i + 1])
                # Find fib swings
                seg = m1_bars[max(0, m1_start - 10):m1_start + 5]
                sw_highs = detect_swing_highs(seg)
                sw_lows = detect_swing_lows(seg)
                if sw_highs and sw_lows:
                    fib_high = sw_highs[-1]["price"]
                    fib_low = min(b["low"] for b in seg)
                    fib_2_0 = fib_expansion(fib_low, fib_high, 2.0)
                    fib_2_5 = fib_expansion(fib_low, fib_high, 2.5)
                    state = "WAIT_ENTRY"
                    log.event(4, "Bullish Manip into FVG", bar["time"],
                              bar["close"], "M1",
                              f"Fib -2.0={fib_2_0:.2f}, -2.5={fib_2_5:.2f}")

            elif bias == "bearish" and bar["close"] > candle_open:
                manip_extreme = max(b["high"] for b in m1_bars[m1_start:i + 1])
                seg = m1_bars[max(0, m1_start - 10):m1_start + 5]
                sw_highs = detect_swing_highs(seg)
                sw_lows = detect_swing_lows(seg)
                if sw_highs and sw_lows:
                    fib_high = max(b["high"] for b in seg)
                    fib_low = sw_lows[-1]["price"]
                    fib_2_0 = fib_expansion(fib_high, fib_low, 2.0)
                    fib_2_5 = fib_expansion(fib_high, fib_low, 2.5)
                    state = "WAIT_ENTRY"
                    log.event(4, "Bearish Manip into FVG", bar["time"],
                              bar["close"], "M1",
                              f"Fib -2.0={fib_2_0:.2f}, -2.5={fib_2_5:.2f}")

        # ── Step 5: M1 MSS or iFVG entry ────────────────────────
        if state == "WAIT_ENTRY":
            recent = m1_bars[max(0, i - 8):i + 1]
            mss = detect_mss(recent)
            ifvgs = detect_ifvg(recent)

            valid_mss = [s for s in mss if s["direction"] == bias]
            valid_ifvg = [s for s in ifvgs if s["direction"] == bias]

            if not (valid_mss or valid_ifvg):
                continue

            trigger = "iFVG" if valid_ifvg else "MSS"
            log.event(5, f"Entry: {trigger}", bar["time"], bar["close"],
                      "M1", f"Entry triggered.")

            if bias == "bullish":
                sl = round(manip_extreme * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"daily_bias": bias, "candle_open": candle_open,
                           "fvg_top": target_fvg["top"],
                           "fvg_bottom": target_fvg["bottom"],
                           "manip_low": manip_extreme,
                           "trigger": trigger})
            else:
                sl = round(manip_extreme * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"daily_bias": bias, "candle_open": candle_open,
                           "fvg_top": target_fvg["top"],
                           "fvg_bottom": target_fvg["bottom"],
                           "manip_high": manip_extreme,
                           "trigger": trigger})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
