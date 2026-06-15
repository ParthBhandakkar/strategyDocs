"""
Strategy: Combining ICT & Footprint Chart
Source: Faiz SMC ("Combining ICT & Footprint Chart To Take High Probability Trades")
Video: https://www.youtube.com/watch?v=Ocu8vSvOGCU

Core Concept:
  ICT key levels + order flow absorption. Sweep + heavy volume + rejection close
  = institutional absorption. Entry at close or 30s chart confirmation.
  TP 1:1.5. Requires volume/delta proxy from price action.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "ICTFootprint"
SYMBOL = "NQ"
TIMEFRAMES = ["M15", "M1"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m15_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: Key ICT levels ──────────────────────────────────────
    # Use daily/session pivots from M15
    m15_lows = detect_swing_lows(m15_bars[-40:])
    m15_highs = detect_swing_highs(m15_bars[-40:])

    key_low = m15_lows[-1]["price"] if m15_lows else None
    key_high = m15_highs[-1]["price"] if m15_highs else None

    log.event(1, "ICT Key Levels Identified",
              m15_bars[-1]["time"] if m15_bars else "",
              key_high or key_low or 0, "M15",
              f"Key high={key_high:.2f}" if key_high else "None"
              f" | Key low={key_low:.2f}" if key_low else "None")

    # ── State Machine on M1 ─────────────────────────────────────────
    state = "WAIT_SWEEP"
    trade_taken = False

    for i in range(5, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 7 or ny.hour >= 14:
            continue
        if trade_taken:
            break

        # ── Step 3: Sweep + absorption proxy ─────────────────────
        if state == "WAIT_SWEEP":
            if key_low and bar["low"] < key_low and bar["close"] > bar["open"]:
                # Swept low + bullish close = potential absorption
                # Check volume proxy (range vs average)
                recent = m1_bars[max(0, i - 10):i]
                avg_range = sum(b["high"] - b["low"] for b in recent) / len(recent)
                body = bar["close"] - bar["open"]
                candle_range = bar["high"] - bar["low"]

                # Wide range + bullish close after sweeping a key low
                if candle_range > avg_range * 1.5 and body > candle_range * 0.5:
                    log.event(2, "Absorption Signal (Bullish)", bar["time"],
                              bar["close"], "M1",
                              f"Swept key low={key_low:.2f}, "
                              f"wide range + bullish close. "
                              f"Proxy: heavy volume/absorption.")

                    sl = round(bar["low"] * 0.9998, 5)
                    tp = round(bar["close"] + (bar["close"] - sl) * 1.5, 5)
                    log.trade("LONG", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"key_level": "low",
                               "swept_price": key_low,
                               "sweep_candle_low": bar["low"],
                               "candle_range": round(candle_range, 2),
                               "avg_range": round(avg_range, 2),
                               "signature": "absorption_bullish"})
                    trade_taken = True
                    break

            elif key_high and bar["high"] > key_high and bar["close"] < bar["open"]:
                recent = m1_bars[max(0, i - 10):i]
                avg_range = sum(b["high"] - b["low"] for b in recent) / len(recent)
                candle_range = bar["high"] - bar["low"]
                body = bar["open"] - bar["close"]

                if candle_range > avg_range * 1.5 and body > candle_range * 0.5:
                    log.event(2, "Absorption Signal (Bearish)", bar["time"],
                              bar["close"], "M1",
                              f"Swept key high={key_high:.2f}, "
                              f"wide range + bearish close.")

                    sl = round(bar["high"] * 1.0002, 5)
                    tp = round(bar["close"] - (sl - bar["close"]) * 1.5, 5)
                    log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"key_level": "high",
                               "swept_price": key_high,
                               "sweep_candle_high": bar["high"],
                               "candle_range": round(candle_range, 2),
                               "avg_range": round(avg_range, 2),
                               "signature": "absorption_bearish"})
                    trade_taken = True
                    break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
