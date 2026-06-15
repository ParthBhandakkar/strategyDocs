"""
Strategy: 10AM PO3 Trading Setup
Source: Faiz SMC ("My One Trading Setup For Life - 10AM PO3")
Video: https://www.youtube.com/watch?v=fAkQOcbChV4

Core Concept:
  4H bias from 2AM/6AM close. 10AM 4H open → 5M left-side liquidity sweep.
  CISD or iFVG entry on 5M. TP 1:2. Partial at 1:1.5.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "TenAMPO3"
SYMBOL = "NQ"
TIMEFRAMES = ["4H", "M5", "M1"]


def determine_bias(h4_bars):
    """2AM vs 6AM 4H candle bias."""
    c2 = c6 = None
    for b in h4_bars:
        h = get_ny_time(b["time"]).hour
        if h == 2:
            c2 = b
        if h == 6:
            c6 = b
        if c2 and c6:
            break
    if not c2 or not c6:
        return None
    if c6["close"] > c2["high"]:
        return "bullish"
    if c6["close"] < c2["low"]:
        return "bearish"
    if c6["high"] > c2["high"] and c6["close"] < c2["high"]:
        return "bearish"
    if c6["low"] < c2["low"] and c6["close"] > c2["low"]:
        return "bullish"
    return "no_trade"


def find_left_swing(bars, start_idx, direction, count=1):
    """Find the nth most recent swing left of a given index."""
    left = bars[:start_idx]
    if direction == "high":
        sw = detect_swing_highs(left)
    else:
        sw = detect_swing_lows(left)
    if len(sw) >= count:
        return sw[-count]
    return sw[-1] if sw else None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "4H")
    m5_bars = get_bars(data_dir, symbol, "M5")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h4_bars or not m5_bars:
        print("No data found")
        return

    # ── Step 1: Daily bias ──────────────────────────────────────────
    bias = determine_bias(h4_bars)
    if bias is None or bias == "no_trade":
        log.event(1, f"Bias: {bias or 'unknown'}", h4_bars[-1]["time"],
                  h4_bars[-1]["close"], "4H", "No trade.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"Daily Bias: {bias.upper()}", h4_bars[-1]["time"],
              h4_bars[-1]["close"], "4H")

    # ── Step 2: 10AM 4H open + left-side 5M swings ─────────────────
    candle_open = 0.0
    candle_time = None
    candle_idx = None
    for i, b in enumerate(h4_bars):
        if get_ny_time(b["time"]).hour == 10 and get_ny_time(b["time"]).minute == 0:
            candle_open = b["open"]
            candle_time = b["time"]
            candle_idx = i
            break

    if not candle_time:
        log.event(2, "10AM Candle Not Found", h4_bars[-1]["time"], 0, "4H")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(2, "10AM 4H Open + Left-Side Swings", candle_time, candle_open, "4H",
              f"Open={candle_open:.2f}. Looking for "
              f"{'5M low below open' if bias == 'bullish' else '5M high above open'}.")

    # Find 5M index for 10AM
    m5_start = next((j for j, b in enumerate(m5_bars) if b["time"] >= candle_time), 0)

    # Find left-side swings on 5M
    if bias == "bullish":
        target_swing = find_left_swing(m5_bars, m5_start, "low", 1)
    else:
        target_swing = find_left_swing(m5_bars, m5_start, "high", 1)

    if not target_swing:
        log.event(3, "No Left-Side Swing Found", candle_time, candle_open, "M5")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(3, f"Target {'Low' if bias=='bullish' else 'High'} on 5M",
              target_swing["time"], target_swing["price"], "M5",
              f"Price={target_swing['price']:.2f}")

    # ── State Machine on M5 ─────────────────────────────────────────
    state = "WAIT_SWEEP"
    sweep_extreme = 0.0
    trade_taken = False

    for i in range(m5_start + 1, len(m5_bars)):
        bar = m5_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 10 or ny.hour >= 14:
            continue
        if trade_taken:
            break

        # ── Step 3: Sweep left-side liquidity ────────────────────
        if state == "WAIT_SWEEP":
            if bias == "bullish" and bar["low"] < target_swing["price"]:
                sweep_extreme = bar["low"]
                state = "WAIT_CISD_IFVG"
                log.event(4, "Left-Side Low Swept (Bullish)", bar["time"],
                          bar["low"], "M5",
                          f"Swept low @ {target_swing['price']:.2f}")
            elif bias == "bearish" and bar["high"] > target_swing["price"]:
                sweep_extreme = bar["high"]
                state = "WAIT_CISD_IFVG"
                log.event(4, "Left-Side High Swept (Bearish)", bar["time"],
                          bar["high"], "M5",
                          f"Swept high @ {target_swing['price']:.2f}")

        # ── Step 4: CISD or iFVG entry ──────────────────────────
        if state == "WAIT_CISD_IFVG":
            recent_m5 = m5_bars[max(0, i - 4):i + 1]
            cisd = [s for s in detect_cisd(recent_m5) if s["direction"] == bias]
            ifvgs = [s for s in detect_ifvg(recent_m5) if s["direction"] == bias]

            if not (cisd or ifvgs):
                continue

            trigger = "CISD" if cisd else "iFVG"
            log.event(5, f"Entry ({trigger})", bar["time"], bar["close"],
                      "M5", f"Entry triggered.")

            if bias == "bullish":
                sl = round(sweep_extreme * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"daily_bias": bias, "candle_open": candle_open,
                           "left_swing": target_swing["price"],
                           "sweep_price": sweep_extreme,
                           "trigger": trigger, "timeframe": "5M"})
            else:
                sl = round(sweep_extreme * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"daily_bias": bias, "candle_open": candle_open,
                           "left_swing": target_swing["price"],
                           "sweep_price": sweep_extreme,
                           "trigger": trigger, "timeframe": "5M"})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
