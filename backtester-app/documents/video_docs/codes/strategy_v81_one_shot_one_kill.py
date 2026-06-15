"""
Strategy: One Shot One Kill (OSOK) — PO3 1M Scalping
Source: Faiz SMC ("How I Make $500/Day Trading ICT Power Of 3! (Insane Winrate)")
Video: https://www.youtube.com/watch?v=yPA1XioVF18

Core Concept:
  1H bias from last 2 candles. D3 candle window.
  Drop to 1M. Look for Judas swing that sweeps liquidity (equal H/Ls)
  to left of 1M candle open. MSS wick (no body closure needed).
  Entry at OB (candle that swept liquidity). 1:2 target.
  If both sides swept, low-probability. Best on NQ.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "OneShotOneKill"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "M1"]


def determine_h1_bias(h1_bars: list):
    """Determine bias from last 2 completed 1H candles."""
    if len(h1_bars) < 3:
        return None, None

    d1 = h1_bars[-3]
    d2 = h1_bars[-2]
    d3_open = h1_bars[-1]["open"]

    if d2["close"] > d1["high"]:
        return "bullish", d3_open
    if d2["close"] < d1["low"]:
        return "bearish", d3_open

    # Failed to close above high = bearish bias
    if d2["high"] > d1["high"] and d2["close"] < d1["high"]:
        return "bearish", d3_open
    # Failed to close below low = bullish bias
    if d2["low"] < d1["low"] and d2["close"] > d1["low"]:
        return "bullish", d3_open

    return None, d3_open


def find_1m_sweep_entry(m1_bars: list, idx: int, direction: str):
    """
    Find a 1M candle that sweeps liquidity opposite to bias direction
    (Judas swing), then the next bar shows MSS wick.
    Returns entry details or None.
    """
    if idx < 2 or idx >= len(m1_bars):
        return None

    bar = m1_bars[idx]
    prev = m1_bars[idx - 1]

    if direction == "bullish":
        # Judas swing: a candle that sweeps a low, then MSS wick up
        lookback = max(0, idx - 10)
        recent_lows = [b["low"] for b in m1_bars[lookback:idx]]
        if recent_lows and prev["low"] < min(recent_lows):
            # The sweep candle becomes the OB
            ob_candle = prev
            # Next candle shows MSS wick (high above ob high)
            if bar["high"] > ob_candle["high"]:
                return {
                    "entry": ob_candle["close"],
                    "sl": ob_candle["low"],
                    "ob_high": ob_candle["high"],
                    "ob_low": ob_candle["low"],
                    "sweep_candle_time": prev["time"]
                }
    else:
        lookback = max(0, idx - 10)
        recent_highs = [b["high"] for b in m1_bars[lookback:idx]]
        if recent_highs and prev["high"] > max(recent_highs):
            ob_candle = prev
            if bar["low"] < ob_candle["low"]:
                return {
                    "entry": ob_candle["close"],
                    "sl": ob_candle["high"],
                    "ob_high": ob_candle["high"],
                    "ob_low": ob_candle["low"],
                    "sweep_candle_time": prev["time"]
                }

    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h1_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: 1H bias ─────────────────────────────────────────────
    bias, d3_open = determine_h1_bias(h1_bars)
    if bias is None:
        log.event(1, "No clear 1H bias", h1_bars[-1]["time"],
                  h1_bars[-1]["close"], "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"1H Bias: {bias.upper()}, D3 Open={d3_open:.2f}",
              h1_bars[-1]["time"], d3_open, "H1")

    # ── Step 2-3: Scan 1M within D3 window ──────────────────────────
    d3_start = h1_bars[-1]["time"]

    for i in range(2, len(m1_bars)):
        ny = get_ny_time(m1_bars[i]["time"])
        if ny.hour < 8 or ny.hour > 16:
            continue

        # Check if we're in the correct 1H candle window
        bar_time = m1_bars[i]["time"]

        # ── Judas swing + MSS wick + OB entry ───────────────────
        entry_info = find_1m_sweep_entry(m1_bars, i, bias)
        if entry_info is None:
            continue

        log.event(2, "Judas Swing Sweep", entry_info["sweep_candle_time"],
                  entry_info["sl"], "M1",
                  f"Sweep opposite {bias.upper()} bias")

        log.event(3, f"MSS Wick + Entry ({bias.upper()})",
                  m1_bars[i]["time"], m1_bars[i]["close"], "M1",
                  f"Entry at OB: {entry_info['entry']:.2f}")

        if bias == "bullish":
            sl = round(entry_info["sl"] * 0.9998, 5)
            tp = round(entry_info["entry"] + (entry_info["entry"] - sl) * 2, 5)
            log.trade("LONG", entry_info["entry"], sl, tp,
                      entry_info["sweep_candle_time"],
                      symbol, STRATEGY_NAME,
                      {"bias": "bullish",
                       "ob_high": entry_info["ob_high"],
                       "ob_low": entry_info["ob_low"],
                       "management": "1:2 target, OSOK model"})
        else:
            sl = round(entry_info["sl"] * 1.0002, 5)
            tp = round(entry_info["entry"] - (sl - entry_info["entry"]) * 2, 5)
            log.trade("SHORT", entry_info["entry"], sl, tp,
                      entry_info["sweep_candle_time"],
                      symbol, STRATEGY_NAME,
                      {"bias": "bearish",
                       "ob_high": entry_info["ob_high"],
                       "ob_low": entry_info["ob_low"],
                       "management": "1:2 target, OSOK model"})
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
