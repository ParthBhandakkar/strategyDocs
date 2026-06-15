"""
Strategy: Mechanical 2-Day Daily Bias Strategy
Source: Faiz SMC ("Best ICT Gold Trading Strategy That Works Everyday! (Insane Winrate)")
Video: https://www.youtube.com/watch?v=bUKt8df141U

Core Concept:
  D1: 2 consecutive bull candles (d2 close > d1 high) = bullish bias for d3.
  Same for bearish. Day 3: sweep left-side 15M pool → 15M MSS/CISD → enter.
  TP = prior day unswept H/L or 1:2/1:3.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "TwoDayBias"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["D1", "M15"]


def determine_daily_bias(d1_bars):
    """Check last 2 daily candles for consecutive confirmation."""
    if len(d1_bars) < 3:
        return None
    d1 = d1_bars[-3]  # day 1
    d2 = d1_bars[-2]  # day 2 (yesterday)
    d3 = d1_bars[-1]  # today

    # Bullish: 2 consecutive bull candles, d2 close > d1 high
    if d1["close"] > d1["open"] and d2["close"] > d2["open"] and d2["close"] > d1["high"]:
        return {"bias": "bullish", "d1": d1, "d2": d2, "d3": d3}

    # Bearish: 2 consecutive bear candles, d2 close < d1 low
    if d1["close"] < d1["open"] and d2["close"] < d2["open"] and d2["close"] < d1["low"]:
        return {"bias": "bearish", "d1": d1, "d2": d2, "d3": d3}

    return None


def find_left_15m_pools(m15_bars, start_idx, bias):
    """Find liquidity pools to the left of start_idx on 15M."""
    left = m15_bars[:start_idx]
    if not left:
        return None, None
    sw_highs = detect_swing_highs(left)
    sw_lows = detect_swing_lows(left)

    if bias == "bullish":
        target = sw_lows[-1]["price"] if sw_lows else None
    else:
        target = sw_highs[-1]["price"] if sw_highs else None
    return sw_highs, sw_lows


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    d1_bars = get_bars(data_dir, symbol, "D1")
    m15_bars = get_bars(data_dir, symbol, "M15")

    if not d1_bars or not m15_bars:
        print("No data found")
        return

    # ── Step 1: Daily bias ──────────────────────────────────────────
    bias_info = determine_daily_bias(d1_bars)
    if not bias_info:
        log.event(1, "No Clear Daily Bias", d1_bars[-1]["time"],
                  d1_bars[-1]["close"], "D1",
                  "No 2-consecutive pattern. Skip.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    bias = bias_info["bias"]
    d3 = bias_info["d3"]
    log.event(1, f"Daily Bias: {bias.upper()}", d3["time"], d3["open"], "D1",
              f"Day 2 close {'above d1 high' if bias=='bullish' else 'below d1 low'}.")

    # ── Step 2: Mark today's open + left-side 15M pools ──────────
    today_open = d3["open"]
    today_date = get_ny_time(d3["time"]).date()

    # Find first 15M bar of today
    today_m15_start = next(
        (i for i, b in enumerate(m15_bars)
         if get_ny_time(b["time"]).date() == today_date),
        None
    )
    if today_m15_start is None:
        log.event(2, "No M15 Data for Today", d3["time"], today_open, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # Find left-side pools
    sw_highs, sw_lows = find_left_15m_pools(m15_bars, today_m15_start, bias)
    target_price = None
    if bias == "bullish" and sw_lows:
        target_price = sw_lows[-1]["price"]
    elif bias == "bearish" and sw_highs:
        target_price = sw_highs[-1]["price"]

    if not target_price:
        log.event(2, "No Left-Side Pool Found", m15_bars[today_m15_start]["time"],
                  today_open, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(2, f"Target {'Low' if bias=='bullish' else 'High'} (Left Side)",
              m15_bars[today_m15_start]["time"], target_price, "M15",
              f"Price={target_price:.2f}. Open={today_open:.2f}")

    # ── State Machine on 15M ────────────────────────────────────────
    state = "WAIT_SWEEP"
    sweep_extreme = 0.0
    trade_taken = False

    for i in range(today_m15_start + 1, len(m15_bars)):
        bar = m15_bars[i]
        ny = get_ny_time(bar["time"])

        if ny.date() != today_date:
            break
        if trade_taken:
            break

        # ── Step 3: Sweep + MSS/CISD ─────────────────────────────
        if state == "WAIT_SWEEP":
            if bias == "bullish" and bar["low"] < target_price:
                sweep_extreme = bar["low"]
                state = "WAIT_CONFIRM"
                log.event(3, "Bullish Sweep of Left-Side Low", bar["time"],
                          bar["low"], "M15",
                          f"Swept low @ {target_price:.2f}")
            elif bias == "bearish" and bar["high"] > target_price:
                sweep_extreme = bar["high"]
                state = "WAIT_CONFIRM"
                log.event(3, "Bearish Sweep of Left-Side High", bar["time"],
                          bar["high"], "M15",
                          f"Swept high @ {target_price:.2f}")

        if state == "WAIT_CONFIRM":
            recent = m15_bars[max(0, i - 4):i + 1]
            mss = [s for s in detect_mss(recent) if s["direction"] == bias]
            cisd = [s for s in detect_cisd(recent) if s["direction"] == bias]

            if not (mss or cisd):
                continue

            trigger = "CISD" if cisd else "MSS"
            log.event(4, f"Entry ({trigger})", bar["time"], bar["close"],
                      "M15", f"Entry triggered.")

            # TP: previous day unswept or 1:2
            prev_day = bias_info["d2"]
            if bias == "bullish":
                tp = max(prev_day["high"], bar["close"] + (bar["close"] - sweep_extreme) * 2)
                sl = round(sweep_extreme * 0.9998, 2)
                tp_final = round(tp, 2)
                log.trade("LONG", bar["close"], sl, tp_final, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"daily_bias": bias, "today_open": today_open,
                           "target_pool": target_price,
                           "sweep_price": sweep_extreme,
                           "trigger": trigger,
                           "prev_day_high": prev_day["high"],
                           "prev_day_low": prev_day["low"]})
            else:
                tp = min(prev_day["low"], bar["close"] - (sweep_extreme - bar["close"]) * 2)
                sl = round(sweep_extreme * 1.0002, 2)
                tp_final = round(tp, 2)
                log.trade("SHORT", bar["close"], sl, tp_final, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"daily_bias": bias, "today_open": today_open,
                           "target_pool": target_price,
                           "sweep_price": sweep_extreme,
                           "trigger": trigger,
                           "prev_day_high": prev_day["high"],
                           "prev_day_low": prev_day["low"]})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
