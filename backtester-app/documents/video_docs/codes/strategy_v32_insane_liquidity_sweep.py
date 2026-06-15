"""
Strategy: Insane ICT Liquidity Sweep Trading Strategy
Source: Faiz SMC ("Insane ICT Liquidity Sweep Trading Strategy That Works Like Magic")
Video: https://www.youtube.com/watch?v=PGK_wp_H_8U

Core Concept:
  15M swings (current day only). Candle sweeps swing → closes opposite color
  (bullish after low sweep, bearish after high sweep). Enter next candle open.
  SL past wick. TP 1:2. Reverse if opposite setup appears.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "InsaneLiquiditySweep"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M15"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    bars = get_bars(data_dir, symbol, "M15")
    if not bars:
        print("No data found")
        return

    # ── State Machine ───────────────────────────────────────────────
    state = "WAIT_SWEEP"
    current_session_day = None
    daily_swing_highs = []
    daily_swing_lows = []
    trade_taken = False
    daily_trades = 0
    last_trade_date = None
    in_position = False
    position_dir = None

    for i in range(2, len(bars) - 1):
        bar = bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 0 or ny.hour >= 24:
            continue

        # Reset daily tracking
        if current_session_day != ny.date():
            current_session_day = ny.date()
            daily_swing_highs = []
            daily_swing_lows = []
            in_position = False
            position_dir = None

        if last_trade_date != ny.date():
            daily_trades = 0
            last_trade_date = ny.date()
        if daily_trades >= 3:
            continue
        if trade_taken and not in_position:
            continue

        # ── Step 1: Track daily 15M swings ─────────────────────────
        sw_h = detect_swing_high_3candle(bars, i)
        sw_l = detect_swing_low_3candle(bars, i)
        if sw_h:
            daily_swing_highs.append(sw_h)
        if sw_l:
            daily_swing_lows.append(sw_l)

        # Get nearest swings
        nearest_high = daily_swing_highs[-1] if daily_swing_highs else None
        nearest_low = daily_swing_lows[-1] if daily_swing_lows else None

        # ── Step 2: Sweep + absorption close ─────────────────────
        if state == "WAIT_SWEEP":
            # Long setup: sweep low + bullish close
            if nearest_low and bar["low"] < nearest_low["price"]:
                if bar["close"] > bar["open"]:
                    log.event(1, "Bullish Absorption (Low Swept)", bar["time"],
                              bar["close"], "M15",
                              f"Swept low @ {nearest_low['price']:.2f}")

                    entry = bars[i + 1]["open"]
                    sl = round(bar["low"] * 0.9998, 2)
                    tp = round(entry + (entry - sl) * 2, 2)

                    log.trade("LONG", entry, sl, tp, bar["time"], symbol,
                              STRATEGY_NAME,
                              {"swept_swing_low": nearest_low["price"],
                               "sweep_candle_low": bar["low"],
                               "absorption_candle": "bullish"})
                    trade_taken = True
                    in_position = True
                    position_dir = "long"
                    daily_trades += 1

                    # Step 3: Enter at next candle open
                    # Already handled - entry = bars[i+1]["open"]
                    break

            # Short setup: sweep high + bearish close
            if nearest_high and bar["high"] > nearest_high["price"]:
                if bar["close"] < bar["open"]:
                    log.event(1, "Bearish Absorption (High Swept)", bar["time"],
                              bar["close"], "M15",
                              f"Swept high @ {nearest_high['price']:.2f}")

                    entry = bars[i + 1]["open"]
                    sl = round(bar["high"] * 1.0002, 2)
                    tp = round(entry - (sl - entry) * 2, 2)

                    log.trade("SHORT", entry, sl, tp, bar["time"], symbol,
                              STRATEGY_NAME,
                              {"swept_swing_high": nearest_high["price"],
                               "sweep_candle_high": bar["high"],
                               "absorption_candle": "bearish"})
                    trade_taken = True
                    in_position = True
                    position_dir = "short"
                    daily_trades += 1
                    break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


def detect_swing_high_3candle(bars, idx):
    if idx < 1 or idx >= len(bars) - 1:
        return None
    c = bars[idx]
    p = bars[idx - 1]
    n = bars[idx + 1]
    if c["high"] > p["high"] and c["high"] > n["high"]:
        return {"price": c["high"], "time": c["time"]}
    return None


def detect_swing_low_3candle(bars, idx):
    if idx < 1 or idx >= len(bars) - 1:
        return None
    c = bars[idx]
    p = bars[idx - 1]
    n = bars[idx + 1]
    if c["low"] < p["low"] and c["low"] < n["low"]:
        return {"price": c["low"], "time": c["time"]}
    return None


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
