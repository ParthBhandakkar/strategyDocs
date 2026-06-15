"""
Strategy: The 1H Pattern Nobody Talks About (1H/1M)
Source: Faiz SMC ("The 1H Pattern Nobody Talks About.. (1H, 1M Strategy)")
Video: https://www.youtube.com/watch?v=f7UXeZ1AZtA

Core Concept:
  1) H1 session open (8AM NY). Mark open price.
  2) M5: nearest unswept swing high/low relative to H1 open.
  3) M1: sweep M5 swing + Fibonacci extension (-2.0 to -2.5 zone).
  4) M1 MSS/IFVG → enter on retest. TP 1:2.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "OneHourPattern"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["H1", "M5", "M1"]


def find_nearest_swing_above(bars: list, price: float) -> dict | None:
    sw = detect_swing_highs(bars)
    above = [s for s in sw if s["price"] > price]
    return min(above, key=lambda x: x["price"]) if above else None


def find_nearest_swing_below(bars: list, price: float) -> dict | None:
    sw = detect_swing_lows(bars)
    below = [s for s in sw if s["price"] < price]
    return max(below, key=lambda x: x["price"]) if below else None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m5_bars = get_bars(data_dir, symbol, "M5")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h1_bars or not m5_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: Find NY 8AM session candle ──────────────────────────
    candle_open = 0.0
    candle_time = None
    for b in h1_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == 8 and ny.minute == 0:
            candle_open = b["open"]
            candle_time = b["time"]
            log.event(1, "NY 8AM Candle Open", b["time"], candle_open, "H1",
                      f"Open price={candle_open:.2f}")
            break

    if not candle_time:
        log.event(1, "8AM Candle Not Found", h1_bars[-1]["time"], 0, "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── Step 2: M5 nearest unswept swing high/low ───────────────────
    m5_left = [b for b in m5_bars if b["time"] < candle_time]
    if len(m5_left) < 10:
        log.event(2, "Insufficient M5 data before open",
                  candle_time, 0, "M5")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    sw_high = find_nearest_swing_above(m5_left, candle_open)
    sw_low = find_nearest_swing_below(m5_left, candle_open)

    if not sw_high and not sw_low:
        log.event(2, "No M5 swing levels found", candle_time, 0, "M5")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(2, "M5 Nearest Unswept Swings", candle_time, candle_open, "M5",
              f"Above open: {sw_high['price']:.2f} @ {sw_high['time']}" if sw_high else "None"
              f" | Below open: {sw_low['price']:.2f} @ {sw_low['time']}" if sw_low else "None")

    # Find the pre-open swing for Fibonacci projection
    fib_swing = None
    if sw_high:
        fib_swing = sw_high
    elif sw_low:
        fib_swing = sw_low

    # ── State Machine on M1 ─────────────────────────────────────────
    state = "WAIT_SWEEP"
    sweep_direction = None
    sweep_extreme = 0.0
    fib_target_zone = None
    trade_taken = False

    m1_start_idx = next(
        (i for i, b in enumerate(m1_bars) if b["time"] >= candle_time), 0
    )

    for i in range(m1_start_idx + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        # Trade between 9:00 and 14:00 NY or 8:00-14:00
        if ny.hour < 8 or ny.hour >= 14:
            continue
        if trade_taken:
            break

        # ── Step 3-4: Sweep M5 swing + Fibonacci projection ──────
        if state == "WAIT_SWEEP":
            sell_swept = sw_high and bar["high"] > sw_high["price"]
            buy_swept = sw_low and bar["low"] < sw_low["price"]

            if sell_swept:
                sweep_direction = "bearish"
                sweep_extreme = bar["high"]
                if fib_swing and fib_swing == sw_high:
                    # Find the structural swing body that broke before open
                    pre_swing_high = fib_swing["price"]
                    # Find a recent M5 swing low for extension calc
                    recent_lows = detect_swing_lows(m5_left[-20:])
                    if recent_lows:
                        pre_swing_low = recent_lows[-1]["price"]
                        ext_2_0 = fib_expansion(pre_swing_high, pre_swing_low, 2.0)
                        ext_2_5 = fib_expansion(pre_swing_high, pre_swing_low, 2.5)
                        fib_target_zone = (min(ext_2_0, ext_2_5),
                                           max(ext_2_0, ext_2_5))
                        log.event(3, "Bearish Sweep + Fib Zone", bar["time"],
                                  bar["high"], "M1",
                                  f"Swept M5 high={sw_high['price']:.2f}. "
                                  f"Fib -2.0 to -2.5: "
                                  f"{fib_target_zone[0]:.2f}-{fib_target_zone[1]:.2f}")
                        state = "WAIT_FIB_TAP"

            elif buy_swept:
                sweep_direction = "bullish"
                sweep_extreme = bar["low"]
                if fib_swing and fib_swing == sw_low:
                    pre_swing_low = fib_swing["price"]
                    recent_highs = detect_swing_highs(m5_left[-20:])
                    if recent_highs:
                        pre_swing_high = recent_highs[-1]["price"]
                        ext_2_0 = fib_expansion(pre_swing_low, pre_swing_high, 2.0)
                        ext_2_5 = fib_expansion(pre_swing_low, pre_swing_high, 2.5)
                        fib_target_zone = (min(ext_2_0, ext_2_5),
                                           max(ext_2_0, ext_2_5))
                        log.event(3, "Bullish Sweep + Fib Zone", bar["time"],
                                  bar["low"], "M1",
                                  f"Swept M5 low={sw_low['price']:.2f}. "
                                  f"Fib -2.0 to -2.5: "
                                  f"{fib_target_zone[0]:.2f}-{fib_target_zone[1]:.2f}")
                        state = "WAIT_FIB_TAP"

        # ── Step 4: Tap fib zone + reversal trigger ─────────────────
        if state == "WAIT_FIB_TAP" and fib_target_zone:
            in_zone = fib_target_zone[0] <= bar["close"] <= fib_target_zone[1]
            if not in_zone:
                continue

            recent = m1_bars[max(0, i - 8):i + 1]
            mss = detect_mss(recent)
            ifvg = detect_ifvg(recent)

            valid_mss = [s for s in mss if s["direction"] == sweep_direction]
            valid_ifvg = [s for s in ifvg if s["direction"] == sweep_direction]

            if not (valid_mss or valid_ifvg):
                continue

            trigger = "MSS" if valid_mss else "IFVG"
            log.event(4, f"Fib Zone Tap + {trigger}", bar["time"],
                      bar["close"], "M1",
                      f"Entry triggered at fib zone with {trigger}.")

            if sweep_direction == "bearish":
                sl = round(sweep_extreme * 1.0002, 2)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 2)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"h1_open": candle_open,
                           "m5_swing_high": sw_high["price"] if sw_high else None,
                           "m5_swing_low": sw_low["price"] if sw_low else None,
                           "fib_zone": fib_target_zone,
                           "sweep_extreme": sweep_extreme,
                           "trigger": trigger})
            else:
                sl = round(sweep_extreme * 0.9998, 2)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 2)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"h1_open": candle_open,
                           "m5_swing_high": sw_high["price"] if sw_high else None,
                           "m5_swing_low": sw_low["price"] if sw_low else None,
                           "fib_zone": fib_target_zone,
                           "sweep_extreme": sweep_extreme,
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
