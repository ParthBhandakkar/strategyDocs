"""
Strategy: ICT Liquidity Sweep Strategy (2025)
Source: Faiz SMC ("Best ICT Liquidity Trading Strategy To Use In 2025!")
Video: https://www.youtube.com/watch?v=F4tcFpgYBdQ

Core Concept:
  Daily 3-candle bias: d2 close > d1 high = bullish;
  d2 close < d1 low = bearish. D3 open reference.
  15M after 9:30 AM NY: sweep liquidity opposite to bias,
  MSS + OB/FVG entry. 1:2-1:3 target. No trade if body doesn't
  close above/below prev candle in pattern.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "ICTLiquiditySweep2025"
SYMBOL = "NQ"
TIMEFRAMES = ["D1", "M15", "M5"]


def daily_bias_3candle(daily_bars: list):
    """3-candle bias: compare candle 2 vs candle 1."""
    if len(daily_bars) < 4:
        return None, None

    d1 = daily_bars[-4]
    d2 = daily_bars[-3]
    d3 = daily_bars[-2]
    d4_open = daily_bars[-1]["open"]

    if d2["close"] > d1["high"] and d3["close"] > d2["high"]:
        return "bullish", d4_open
    if d2["close"] < d1["low"] and d3["close"] < d2["low"]:
        return "bearish", d4_open

    return None, d4_open


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    daily_bars = get_bars(data_dir, symbol, "D1")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m5_bars = get_bars(data_dir, symbol, "M5")

    if not daily_bars or not m15_bars:
        print("No data found")
        return

    # ── Step 1: Bias ────────────────────────────────────────────────
    bias, d4_open = daily_bias_3candle(daily_bars)
    if bias is None:
        log.event(1, "No clear bias (avoid trade)", daily_bars[-1]["time"],
                  daily_bars[-1]["close"], "D1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"Daily Bias: {bias.upper()}, D4 Open={d4_open:.2f}",
              daily_bars[-1]["time"], d4_open, "D1")

    # ── Step 2-3: 15M after 9:30AM ──────────────────────────────────
    for i in range(3, len(m15_bars)):
        ny = get_ny_time(m15_bars[i]["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 16:
            break

        bar = m15_bars[i]

        # ── Sweep opposite to bias ──────────────────────────────
        if bias == "bullish":
            lookback = max(0, i - 8)
            recent = m15_bars[lookback:i]
            recent_low = min(b["low"] for b in recent)
            if bar["low"] >= recent_low:
                continue

            log.event(2, "Sell-Side Liquidity Swept", bar["time"],
                      bar["low"], "M15")

            # MSS check
            for j in range(i + 1, min(i + 6, len(m15_bars))):
                seg = m15_bars[max(0, j - 4):j + 1]
                if len(seg) < 3:
                    continue

                bar2 = m15_bars[j]
                recent_h = max(b["high"] for b in seg[:-1])
                if bar2["close"] > bar2["open"] and bar2["close"] > recent_h:
                    log.event(3, "MSS + Entry (Long)", bar2["time"],
                              bar2["close"], "M15")

                    sl = round(bar2["low"] * 0.9998, 5)
                    tp = round(bar2["close"] + (bar2["close"] - sl) * 2.5, 5)
                    log.trade("LONG", bar2["close"], sl, tp, bar2["time"],
                              symbol, STRATEGY_NAME,
                              {"bias": "bullish",
                               "management": "1:2-1:3 target"})
                    break
            break

        else:
            lookback = max(0, i - 8)
            recent = m15_bars[lookback:i]
            recent_high = max(b["high"] for b in recent)
            if bar["high"] <= recent_high:
                continue

            log.event(2, "Buy-Side Liquidity Swept", bar["time"],
                      bar["high"], "M15")

            for j in range(i + 1, min(i + 6, len(m15_bars))):
                seg = m15_bars[max(0, j - 4):j + 1]
                bar2 = m15_bars[j]
                recent_l = min(b["low"] for b in seg[:-1])
                if bar2["close"] < bar2["open"] and bar2["close"] < recent_l:
                    log.event(3, "MSS + Entry (Short)", bar2["time"],
                              bar2["close"], "M15")

                    sl = round(bar2["high"] * 1.0002, 5)
                    tp = round(bar2["close"] - (sl - bar2["close"]) * 2.5, 5)
                    log.trade("SHORT", bar2["close"], sl, tp, bar2["time"],
                              symbol, STRATEGY_NAME,
                              {"bias": "bearish",
                               "management": "1:2-1:3 target"})
                    break
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
