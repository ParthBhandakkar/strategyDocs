"""
Strategy: Simple ICT $1000/Day Scalping (NQ)
Source: Faiz SMC ("Simple ICT Trading Strategy Makes $1,000/Day")
Video: https://www.youtube.com/watch?v=IJm1HLHNxY8

Core Concept:
  NQ. Daily bias + PD array identification. 1H builds engineered
  liquidity (equal H/Ls) inside daily PD array before 9:30 AM.
  9:30 AM sweep of engineered liquidity (Judas swing).
  Drop to 1M for autoblock/inversion entry. CSOD confirmation.
  BE at closest H/L. 1:2 target.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "ThousandDayScalp"
SYMBOL = "NQ"
TIMEFRAMES = ["D1", "H1", "M1"]


def find_daily_pd_array(daily_bars: list, lookback: int = 5):
    """
    Find daily PD array (FVG or OB) that price is currently within.
    Returns (top, bottom, type).
    """
    seg = daily_bars[-lookback:]
    fvgs = detect_fvg(seg)
    if fvgs:
        fvg = fvgs[-1]
        return fvg["top"], fvg["bottom"], "FVG"

    # Check for order blocks
    for j in range(1, len(seg) - 1):
        if seg[j]["close"] > seg[j]["open"] and seg[j - 1]["close"] < seg[j - 1]["open"]:
            if seg[j - 1]["low"] <= seg[j]["open"]:
                return seg[j]["high"], seg[j - 1]["low"], "OB"

    return None, None, None


def find_engineered_liquidity(h1_bars: list, pd_top: float, pd_bottom: float):
    """
    Find equal highs/lows built within the PD array on 1H.
    Returns (eq_high, eq_low) or (None, None).
    """
    if len(h1_bars) < 6:
        return None, None

    # Check bars within PD array
    inside = [b for b in h1_bars[-12:]
              if pd_bottom <= b["low"] and b["high"] <= pd_top]

    if len(inside) < 3:
        return None, None

    # Look for equal highs (within 0.1% tolerance)
    highs = [b["high"] for b in inside]
    lows = [b["low"] for b in inside]

    eq_high = None
    for i in range(len(highs)):
        for j in range(i + 1, len(highs)):
            if abs(highs[i] - highs[j]) / highs[i] < 0.001:
                eq_high = max(highs[i], highs[j])
                break

    eq_low = None
    for i in range(len(lows)):
        for j in range(i + 1, len(lows)):
            if abs(lows[i] - lows[j]) / lows[i] < 0.001:
                eq_low = min(lows[i], lows[j])
                break

    return eq_high, eq_low


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    daily_bars = get_bars(data_dir, symbol, "D1")
    h1_bars = get_bars(data_dir, symbol, "H1")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not daily_bars or not h1_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: Daily bias + PD array ──────────────────────────────
    d1 = daily_bars[-1]
    d2 = daily_bars[-2] if len(daily_bars) >= 2 else None
    bias = "bullish" if d1["close"] > d1["open"] else "bearish"

    log.event(1, f"Daily Bias: {bias.upper()}", d1["time"],
              d1["close"], "D1")

    pd_top, pd_bottom, pd_type = find_daily_pd_array(daily_bars)
    if pd_top is not None:
        log.event(2, f"Daily PD Array ({pd_type})", d1["time"],
                  pd_top, "D1",
                  f"Top={pd_top:.2f}, Bottom={pd_bottom:.2f}")
    else:
        log.event(2, "No daily PD array found", d1["time"], 0, "D1")

    # ── Step 2: Engineered liquidity inside PD array ────────────────
    eq_high, eq_low = find_engineered_liquidity(
        h1_bars, pd_top or d1["high"], pd_bottom or d1["low"]
    )

    if eq_high is None and eq_low is None:
        log.event(3, "No engineered liquidity found inside PD array",
                  h1_bars[-1]["time"], 0, "H1",
                  "Skipping setup")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(3, "Engineered Liquidity (1H)", h1_bars[-1]["time"],
              eq_high or eq_low, "H1",
              f"Equal High={eq_high}, Equal Low={eq_low}")

    # ── Step 3-4: 9:30 AM sweep → M1 entry ─────────────────────────
    swept = False

    for i in range(5, len(m1_bars)):
        ny = get_ny_time(m1_bars[i]["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11:
            break

        bar = m1_bars[i]

        # ── Sweep ──────────────────────────────────────────────
        if not swept:
            if eq_low and bar["low"] < eq_low:
                log.event(4, "9:30AM: Low Swept", bar["time"],
                          bar["low"], "M1", "Engineered liquidity sweep")
                swept = True
                sweep_dir = "bullish"
            elif eq_high and bar["high"] > eq_high:
                log.event(4, "9:30AM: High Swept", bar["time"],
                          bar["high"], "M1", "Engineered liquidity sweep")
                swept = True
                sweep_dir = "bearish"
            continue

        # ── After sweep: CSOD + autoblock/inversion ────────────
        seg = m1_bars[max(0, i - 7):i + 1]
        if len(seg) < 3:
            continue

        bar_now = m1_bars[i]

        # CSOD: candle closes above sweep candle's high
        if sweep_dir == "bullish":
            # Find the sweep candle
            sweep_candle = m1_bars[i - 1] if i > 0 else None
            if sweep_candle is not None and bar_now["close"] > sweep_candle["high"]:
                log.event(5, "CSOD Confirmed (Long)", bar_now["time"],
                          bar_now["close"], "M1")

                sl = round(bar_now["low"] * 0.9998, 5)
                tp = round(bar_now["close"] + (bar_now["close"] - sl) * 2, 5)

                log.trade("LONG", bar_now["close"], sl, tp, bar_now["time"],
                          symbol, STRATEGY_NAME,
                          {"setup": "LiquiditySweep+CSOD",
                           "daily_bias": bias,
                           "engineered_low": eq_low,
                           "management": "BE at closest H/L, 1:2 TP"})
                break
        else:
            sweep_candle = m1_bars[i - 1] if i > 0 else None
            if sweep_candle is not None and bar_now["close"] < sweep_candle["low"]:
                log.event(5, "CSOD Confirmed (Short)", bar_now["time"],
                          bar_now["close"], "M1")

                sl = round(bar_now["high"] * 1.0002, 5)
                tp = round(bar_now["close"] - (sl - bar_now["close"]) * 2, 5)

                log.trade("SHORT", bar_now["close"], sl, tp, bar_now["time"],
                          symbol, STRATEGY_NAME,
                          {"setup": "LiquiditySweep+CSOD",
                           "daily_bias": bias,
                           "engineered_high": eq_high,
                           "management": "BE at closest H/L, 1:2 TP"})
                break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
