"""
Strategy: The Only GOLD Trading Strategy You Need In 2026
Source: Faiz SMC ("The Only GOLD Trading Strategy You Need In 2026! (Stupid Simple)")
Video: https://www.youtube.com/watch?v=W6Cd0yiOTtc

Core Concept:
  H1 open → M5 unswept swing levels → M1 sweep + fib -2.0/-2.5 zone.
  MSS/CISD entry. Discount for longs, premium for shorts.
  Max 3 trades/day (one per session: Asia, London, NY).
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "GoldOnly2026"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["H1", "M5", "M1"]


def find_nearest_unswept_swing_above(bars: list, price: float) -> dict | None:
    sw = detect_swing_highs(bars)
    above = [s for s in sw if s["price"] > price]
    return min(above, key=lambda x: x["price"]) if above else None


def find_nearest_unswept_swing_below(bars: list, price: float) -> dict | None:
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

    # ── Step 1: H1 open ─────────────────────────────────────────────
    session_hours = [2, 4, 8, 5, 6]
    candle_open = 0.0
    candle_time = None
    for b in h1_bars:
        ny = get_ny_time(b["time"])
        if ny.hour in session_hours and ny.minute == 0:
            candle_open = b["open"]
            candle_time = b["time"]
            log.event(1, f"H1 Session Open ({ny.hour}:00 NY)", b["time"],
                      candle_open, "H1",
                      f"Open price={candle_open:.2f}")
            break

    if not candle_time:
        log.event(1, "No Session Candle Found", h1_bars[-1]["time"], 0, "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── Step 2: M5 nearest unswept swings ───────────────────────────
    m5_left = [b for b in m5_bars if b["time"] < candle_time]
    if len(m5_left) < 10:
        log.event(2, "Insufficient M5 data", candle_time, 0, "M5")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    sw_high = find_nearest_unswept_swing_above(m5_left, candle_open)
    sw_low = find_nearest_unswept_swing_below(m5_left, candle_open)

    log.event(2, "M5 Unswept Swings", candle_time, candle_open, "M5",
              f"Above={sw_high['price']:.2f}" if sw_high else "None above"
              f" | Below={sw_low['price']:.2f}" if sw_low else "None below")

    if not sw_high and not sw_low:
        log.event(2, "No M5 swing levels found", candle_time, 0, "M5")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── State Machine on M1 ─────────────────────────────────────────
    state = "WAIT_SWEEP"
    sweep_direction = None
    sweep_info = {}
    trade_taken = False
    daily_trades = 0
    last_trade_date = None

    m1_start = next(
        (i for i, b in enumerate(m1_bars) if b["time"] >= candle_time), 0
    )

    for i in range(m1_start + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 7 or ny.hour >= 14:
            continue
        if trade_taken:
            break

        if last_trade_date != ny.date():
            daily_trades = 0
            last_trade_date = ny.date()
        if daily_trades >= 3:
            log.event(5, "Daily Trade Limit (3) Reached", bar["time"],
                      bar["close"], "M1")
            break

        # ── Step 3: Sweep + fib zone ───────────────────────────────
        if state == "WAIT_SWEEP":
            if sw_high and bar["high"] > sw_high["price"]:
                sweep_direction = "bearish"
                sweep_info = {"swept_level": sw_high["price"],
                              "extreme": bar["high"]}

                # Fib extension from pre-swing
                recent_lows = detect_swing_lows(m5_left[-20:])
                if recent_lows:
                    fib2 = fib_expansion(sw_high["price"], recent_lows[-1]["price"], 2.0)
                    fib25 = fib_expansion(sw_high["price"], recent_lows[-1]["price"], 2.5)
                    sweep_info["fib_zone"] = (min(fib2, fib25), max(fib2, fib25))

                state = "WAIT_FIB_REVERSAL"
                log.event(3, "Bearish Sweep (Premium)", bar["time"],
                          bar["high"], "M1",
                          f"Swept M5 high={sw_high['price']:.2f}")

            elif sw_low and bar["low"] < sw_low["price"]:
                sweep_direction = "bullish"
                sweep_info = {"swept_level": sw_low["price"],
                              "extreme": bar["low"]}

                recent_highs = detect_swing_highs(m5_left[-20:])
                if recent_highs:
                    fib2 = fib_expansion(sw_low["price"], recent_highs[-1]["price"], 2.0)
                    fib25 = fib_expansion(sw_low["price"], recent_highs[-1]["price"], 2.5)
                    sweep_info["fib_zone"] = (min(fib2, fib25), max(fib2, fib25))

                state = "WAIT_FIB_REVERSAL"
                log.event(3, "Bullish Sweep (Discount)", bar["time"],
                          bar["low"], "M1",
                          f"Swept M5 low={sw_low['price']:.2f}")

        # ── Step 4: Fib zone + MSS/CISD entry ──────────────────────
        if state == "WAIT_FIB_REVERSAL":
            fib_zone = sweep_info.get("fib_zone")
            if fib_zone:
                in_zone = fib_zone[0] <= bar["close"] <= fib_zone[1]
                if not in_zone:
                    continue

            recent = m1_bars[max(0, i - 8):i + 1]
            mss = [s for s in detect_mss(recent)
                   if s["direction"] == sweep_direction]
            cisd = [s for s in detect_cisd(recent)
                    if s["direction"] == sweep_direction]

            if not (mss or cisd):
                continue

            trigger = "CISD" if cisd else "MSS"
            entry = bar["close"]
            log.event(4, f"Entry via {trigger}", bar["time"], entry, "M1",
                      f"{sweep_direction.upper()} triggered.")

            if sweep_direction == "bearish":
                sl = round(sweep_info["extreme"] * 1.0002, 2)
                tp = round(entry - (sl - entry) * 2, 2)
                log.trade("SHORT", entry, sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"h1_open": candle_open, "trigger": trigger,
                           "swept_level": sweep_info["swept_level"],
                           "fib_zone": sweep_info.get("fib_zone"),
                           "session": f"{get_ny_time(candle_time).hour}:00"})
            else:
                sl = round(sweep_info["extreme"] * 0.9998, 2)
                tp = round(entry + (entry - sl) * 2, 2)
                log.trade("LONG", entry, sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"h1_open": candle_open, "trigger": trigger,
                           "swept_level": sweep_info["swept_level"],
                           "fib_zone": sweep_info.get("fib_zone"),
                           "session": f"{get_ny_time(candle_time).hour}:00"})

            daily_trades += 1
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
