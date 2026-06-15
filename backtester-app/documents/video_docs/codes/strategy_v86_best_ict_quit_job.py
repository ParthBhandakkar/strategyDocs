"""
Strategy: Best ICT Trading Strategy — PO3 Weekly/Daily
Source: Faiz SMC ("Best ICT Trading Strategy! (Quit Your Job In 60 Days!)")
Video: https://www.youtube.com/watch?v=RwscctjAhaw

Core Concept:
  Weekly or Daily bias using 2-candle pattern (close > high = bullish,
  close < low = bearish). Trade D3.
  Weekly: 4H for liquidity, 15M for MSS entry.
  Daily: 1H for liquidity, 5M for MSS entry.
  Sweep opposite to bias → MSS → entry. Avoid Fridays.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "BestICTQuitJob60"
SYMBOL = "NQ"
TIMEFRAMES = ["W1", "D1", "H4", "H1", "M15", "M5"]


def determine_bias_2candle(bars: list):
    """2-candle pattern: d2 close > d1 high = bullish, etc."""
    if len(bars) < 3:
        return None, None

    d1 = bars[-3]
    d2 = bars[-2]
    d3_open = bars[-1]["open"]

    if d2["close"] > d1["high"]:
        return "bullish", d3_open
    if d2["close"] < d1["low"]:
        return "bearish", d3_open

    return None, d3_open


def find_liquidity_swing(bars: list, d3_open: float, direction: str):
    """Find sweep of liquidity opposite to bias direction."""
    for i in range(1, len(bars)):
        if direction == "bullish":
            recent = bars[max(0, i - 8):i]
            if recent and bars[i]["low"] < min(b["low"] for b in recent):
                return bars[i]["low"], i
        else:
            recent = bars[max(0, i - 8):i]
            if recent and bars[i]["high"] > max(b["high"] for b in recent):
                return bars[i]["high"], i
    return None, None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    # Weekly bias → 4H/15M
    w1_bars = get_bars(data_dir, symbol, "W1")
    d1_bars = get_bars(data_dir, symbol, "D1")

    if not d1_bars:
        print("No data found")
        return

    # Try weekly first, fall back to daily
    bias, bias_open = determine_bias_2candle(w1_bars or [])
    timeframe_label = "Weekly"

    if bias is None:
        bias, bias_open = determine_bias_2candle(d1_bars or [])
        timeframe_label = "Daily"

    if bias is None:
        log.event(1, "No clear bias (weekly or daily)",
                  d1_bars[-1]["time"], d1_bars[-1]["close"], "W1/D1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"{timeframe_label} Bias: {bias.upper()}, "
              f"Open={bias_open:.2f}",
              d1_bars[-1]["time"], bias_open, timeframe_label[:2])

    # ── Use appropriate TFs ─────────────────────────────────────────
    if timeframe_label == "Weekly":
        liq_bars = get_bars(data_dir, symbol, "H4")
        entry_bars = get_bars(data_dir, symbol, "M15")
        liq_tf = "H4"
        entry_tf = "M15"
    else:
        liq_bars = get_bars(data_dir, symbol, "H1")
        entry_bars = get_bars(data_dir, symbol, "M5")
        liq_tf = "H1"
        entry_tf = "M5"

    if not liq_bars or not entry_bars:
        print("Insufficient data")
        return

    # ── Find sweep on liquidity TF ──────────────────────────────────
    sweep_level, sweep_idx = find_liquidity_swing(liq_bars, bias_open, bias)
    if sweep_level is None:
        log.event(2, f"No sweep on {liq_tf}", liq_bars[-1]["time"], 0, liq_tf)
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    sweep_time = liq_bars[sweep_idx]["time"]
    log.event(2, f"Sweep on {liq_tf} ({bias.upper()})",
              sweep_time, sweep_level, liq_tf)

    # ── Find entry on entry TF ──────────────────────────────────────
    for i in range(3, len(entry_bars)):
        if entry_bars[i]["time"] < sweep_time:
            continue

        bar = entry_bars[i]
        seg = entry_bars[max(0, i - 6):i + 1]
        if len(seg) < 3:
            continue

        recent_high = max(b["high"] for b in seg[:-1])
        recent_low = min(b["low"] for b in seg[:-1])

        if bias == "bullish":
            if bar["close"] > bar["open"] and bar["close"] > recent_high:
                log.event(3, f"MSS + Entry on {entry_tf} (Long)",
                          bar["time"], bar["close"], entry_tf)
                sl = round(bar["low"] * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"bias_timeframe": timeframe_label,
                           "liq_tf": liq_tf, "entry_tf": entry_tf,
                           "management": "1:2 target"})
                break
        else:
            if bar["close"] < bar["open"] and bar["close"] < recent_low:
                log.event(3, f"MSS + Entry on {entry_tf} (Short)",
                          bar["time"], bar["close"], entry_tf)
                sl = round(bar["high"] * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"bias_timeframe": timeframe_label,
                           "liq_tf": liq_tf, "entry_tf": entry_tf,
                           "management": "1:2 target"})
                break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
