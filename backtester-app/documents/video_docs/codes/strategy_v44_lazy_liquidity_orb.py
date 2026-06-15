"""
Strategy: The Lazy Liquidity Strategy (Mechanical ORB Setup)
Source: Faiz SMC ("The Laziest Liquidity Trading Strategy Making $15,000/Month")
Video: https://www.youtube.com/watch?v=YKbkZ4eRd04

Core Concept:
  3AM NY 15M anchor candle (London open). Body close breakout → enter.
  SL at opposite anchor side. BE at 1:1, TP at 1:2.
  OCO reversal allowed. GBP/USD only.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "LazyLiquidityORB"
SYMBOL = "GBPUSD"
TIMEFRAMES = ["M15"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    bars = get_bars(data_dir, symbol, "M15")
    if not bars:
        print("No data found")
        return

    # ── Step 1: Find 3AM anchor candle ──────────────────────────────
    anchor_idx = None
    for i, b in enumerate(bars):
        ny = get_ny_time(b["time"])
        if ny.hour == 3 and ny.minute == 0:
            anchor_idx = i
            break

    if anchor_idx is None or anchor_idx + 1 >= len(bars):
        log.event(0, "3AM Anchor Candle Not Found", bars[-1]["time"], 0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    anchor_high = bars[anchor_idx]["high"]
    anchor_low = bars[anchor_idx]["low"]
    log.event(1, "London 3AM Anchor Candle", bars[anchor_idx]["time"],
              anchor_high, "M15",
              f"High={anchor_high:.5f}, Low={anchor_low:.5f}")

    # ── Step 2-6: Wait for body close breakout ──────────────────────
    trade_taken = False

    for i in range(anchor_idx + 1, len(bars)):
        bar = bars[i]
        ny = get_ny_time(bar["time"])
        # Only trade London session (3AM - 7AM NY)
        if ny.hour < 3 or ny.hour >= 7:
            continue
        if trade_taken:
            break

        # Body close breakout check
        if bar["close"] > anchor_high and bar["close"] > bar["open"]:
            # Bullish breakout
            dist_above = bar["close"] - anchor_high
            if dist_above < (anchor_high - anchor_low) * 0.5:
                # Aggressive: close just past boundary
                entry = bar["close"]
                entry_type = "aggressive (close)"
            else:
                # Retest: limit at anchor high
                entry = anchor_high
                entry_type = "retest limit"

            sl = round(anchor_low * 0.9998, 5)
            tp = round(entry + (entry - sl) * 2, 5)

            log.event(2, f"Bullish Breakout ({entry_type})", bar["time"],
                      bar["close"], "M15",
                      f"Body close above anchor high={anchor_high:.5f}")

            log.trade("LONG", entry, sl, tp, bar["time"], symbol,
                      STRATEGY_NAME,
                      {"anchor_high": anchor_high, "anchor_low": anchor_low,
                       "breakout_candle_high": bar["high"],
                       "breakout_candle_low": bar["low"],
                       "entry_type": entry_type,
                       "management": "BE at 1:1, TP at 1:2"})
            trade_taken = True
            break

        elif bar["close"] < anchor_low and bar["close"] < bar["open"]:
            dist_below = anchor_low - bar["close"]
            if dist_below < (anchor_high - anchor_low) * 0.5:
                entry = bar["close"]
                entry_type = "aggressive (close)"
            else:
                entry = anchor_low
                entry_type = "retest limit"

            sl = round(anchor_high * 1.0002, 5)
            tp = round(entry - (sl - entry) * 2, 5)

            log.event(2, f"Bearish Breakout ({entry_type})", bar["time"],
                      bar["close"], "M15",
                      f"Body close below anchor low={anchor_low:.5f}")

            log.trade("SHORT", entry, sl, tp, bar["time"], symbol,
                      STRATEGY_NAME,
                      {"anchor_high": anchor_high, "anchor_low": anchor_low,
                       "breakout_candle_high": bar["high"],
                       "breakout_candle_low": bar["low"],
                       "entry_type": entry_type,
                       "management": "BE at 1:1, TP at 1:2"})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
