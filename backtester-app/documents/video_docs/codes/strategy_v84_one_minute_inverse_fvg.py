"""
Strategy: 1-Minute Scalping (Inverse FVG)
Source: Faiz SMC ("Easy ICT 1 Minute Timeframe Trading Strategy That Works! (High Winrate)")
Video: https://www.youtube.com/watch?v=g7MxWxQ99_4

Core Concept:
  HTF bias using external-to-internal liquidity method (equal H/Ls).
  1M after 9:30 AM NY: sweep opposite to bias.
  All FVGs in the leg must be inversed before entry.
  Entry on closure or retest of inversed FVG.
  40% partial at 1:1, hold rest to DOL.
  Invalid if closest liquidity hit before entry completes.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "OneMinuteInverseFVG"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "M1"]


def find_htf_bias(h1_bars: list):
    """External-to-internal bias: check equal H/L sweeps."""
    if len(h1_bars) < 8:
        return None, None, None

    # Look for equal highs/lows
    highs = [b["high"] for b in h1_bars[-8:]]
    lows = [b["low"] for b in h1_bars[-8:]]

    eq_high = None
    eq_low = None

    for i in range(len(highs)):
        for j in range(i + 1, len(highs)):
            if abs(highs[i] - highs[j]) / highs[i] < 0.001:
                eq_high = highs[i]
            if abs(lows[i] - lows[j]) / lows[i] < 0.001:
                eq_low = lows[i]

    # If equal highs were swept, target equal lows = bullish
    last_bar = h1_bars[-1]
    if eq_high and last_bar["high"] > eq_high:
        return "bullish", eq_low, eq_high

    # If equal lows were swept, target equal highs = bearish
    if eq_low and last_bar["low"] < eq_low:
        return "bearish", eq_low, eq_high

    return None, None, None


def all_fvgs_inversed(bars: list, fvgs: list, direction: str, bar_close: float):
    """Check if all FVGs in the set have been inversed."""
    for fvg in fvgs:
        if direction == "bullish":
            if bar_close <= fvg["top"]:
                return False
        else:
            if bar_close >= fvg["bottom"]:
                return False
    return True


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m1_bars:
        print("No data found")
        return

    # ── Step 1: HTF bias ────────────────────────────────────────────
    bias, target_level, swept_level = find_htf_bias(h1_bars or [])
    if bias is None:
        log.event(1, "No clear HTF bias (no equal H/L sweep)",
                  m1_bars[-1]["time"], 0, "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"Bias: {bias.upper()}, Target: {target_level}",
              m1_bars[-1]["time"], target_level or 0, "H1")

    # ── Step 2-3: 1M after 9:30 AM ──────────────────────────────────
    for i in range(5, len(m1_bars)):
        ny = get_ny_time(m1_bars[i]["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11 and ny.minute > 30:
            break

        bar = m1_bars[i]

        # ── Opposite sweep ──────────────────────────────────────
        lookback = max(0, i - 15)
        recent_low = min(b["low"] for b in m1_bars[lookback:i])
        recent_high = max(b["high"] for b in m1_bars[lookback:i])

        if bias == "bullish" and bar["low"] < recent_low:
            sweep_idx = i
            log.event(2, "Sell-Side Sweep (opposite bias)",
                      bar["time"], bar["low"], "M1")
        elif bias == "bearish" and bar["high"] > recent_high:
            sweep_idx = i
            log.event(2, "Buy-Side Sweep (opposite bias)",
                      bar["time"], bar["high"], "M1")
        else:
            continue

        # ── Find FVGs in the leg since sweep ────────────────────
        for j in range(sweep_idx + 1, min(sweep_idx + 15, len(m1_bars))):
            bar2 = m1_bars[j]
            seg = m1_bars[sweep_idx:j + 1]
            fvgs = detect_fvg(seg)

            if not fvgs:
                continue

            if not all_fvgs_inversed(seg, fvgs, bias, bar2["close"]):
                continue

            log.event(3, f"All FVGs Inversed ({bias.upper()})",
                      bar2["time"], bar2["close"], "M1",
                      f"FVGs in leg: {len(fvgs)}")

            if bias == "bullish":
                sl = round(bar2["low"] * 0.9998, 5)
                tp = round(target_level, 5) if target_level else \
                     round(bar2["close"] + (bar2["close"] - sl) * 2, 5)
                log.trade("LONG", bar2["close"], sl, tp, bar2["time"],
                          symbol, STRATEGY_NAME,
                          {"bias": "bullish", "swept_level": swept_level,
                           "target_level": target_level,
                           "fvgs_in_leg": len(fvgs),
                           "management": "40% at 1:1, hold to DOL"})
            else:
                sl = round(bar2["high"] * 1.0002, 5)
                tp = round(target_level, 5) if target_level else \
                     round(bar2["close"] - (sl - bar2["close"]) * 2, 5)
                log.trade("SHORT", bar2["close"], sl, tp, bar2["time"],
                          symbol, STRATEGY_NAME,
                          {"bias": "bearish", "swept_level": swept_level,
                           "target_level": target_level,
                           "fvgs_in_leg": len(fvgs),
                           "management": "40% at 1:1, hold to DOL"})
            break
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
