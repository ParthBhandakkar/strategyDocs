"""
Strategy: ICT Daily Bias Guide
Source: Faiz SMC ("I Simplified ICT Daily Bias..")
Video: https://www.youtube.com/watch?v=Rf2Q46dQcSk

Core Concept:
  Determine daily bias (bullish/bearish) using four methods:
  1) Candle Closure: Compare consecutive daily closes.
  2) Swing H/L Draw on Liquidity: 3-day swing high/low targets.
  3) Discretionary: Liquidity sweep → FVG tap, external to internal.
  4) External to Internal: Sweep external liquidity → inverse FVG.
  Bias confirmed by 1H market structure shift.
  Outputs bias direction with optional trade entry using Judas Swing
  after 9:30 AM NY.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "DailyBiasGuide"
SYMBOL = "NQ"
TIMEFRAMES = ["D1", "H1", "M15", "M1"]


def candle_closure_bias(daily_bars: list):
    """Method 1: Compare consecutive daily closes."""
    if len(daily_bars) < 3:
        return None

    d1 = daily_bars[-3]
    d2 = daily_bars[-2]
    d3 = daily_bars[-1]

    # If d2 closes below d1 low, d3 likely bearish
    if d2["close"] < d1["low"]:
        return "bearish", "CandleClosure: d2 closed below d1 low"
    # If d2 closes above d1 high, d3 likely bullish
    if d2["close"] > d1["high"]:
        return "bullish", "CandleClosure: d2 closed above d1 high"

    return None, None


def swing_hl_bias(daily_bars: list):
    """Method 2: 3-day swing high/low target for 4th day."""
    if len(daily_bars) < 4:
        return None, None

    last_3 = daily_bars[-4:-1]
    if len(last_3) < 3:
        return None, None

    # Find swing low: middle bar is the lowest of 3
    if last_3[1]["low"] < last_3[0]["low"] and last_3[1]["low"] < last_3[2]["low"]:
        target = last_3[1]["high"]
        return "bullish", f"SwingHL: swing low, target high={target:.2f}"

    # Find swing high: middle bar is the highest of 3
    if last_3[1]["high"] > last_3[0]["high"] and last_3[1]["high"] > last_3[2]["high"]:
        target = last_3[1]["low"]
        return "bearish", f"SwingHL: swing high, target low={target:.2f}"

    return None, None


def check_1h_mss(bars_h1: list):
    """Check 1H market structure shift for bias confirmation."""
    if len(bars_h1) < 6:
        return None

    recent = bars_h1[-6:]

    # Look for consecutive higher highs / higher lows (bullish)
    highs = [b["high"] for b in recent]
    lows = [b["low"] for b in recent]

    if highs[-1] > highs[-2] > highs[-3] and lows[-1] > lows[-2]:
        return "bullish"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2] < lows[-3]:
        return "bearish"

    return None


def external_to_internal_bias(m15_bars: list, lookback: int = 24):
    """
    Method 4: External liquidity sweep + FVG inversion.
    """
    seg = m15_bars[-lookback:]
    if len(seg) < 6:
        return None

    recent_high = max(b["high"] for b in seg)
    recent_low = min(b["low"] for b in seg)
    last_bar = seg[-1]

    # Check if external liquidity was swept (price went past recent H/L
    # and then reversed strong)
    swept_high = last_bar["high"] > recent_high and last_bar["close"] < last_bar["open"]
    swept_low = last_bar["low"] < recent_low and last_bar["close"] > last_bar["open"]

    if swept_low:
        return "bullish"
    if swept_high:
        return "bearish"

    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    daily_bars = get_bars(data_dir, symbol, "D1")
    h1_bars = get_bars(data_dir, symbol, "H1")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not daily_bars or not m1_bars:
        print("No data found")
        return

    # ── Determine daily bias using all 4 methods ────────────────────
    biases = []

    # Method 1
    bias, reason = candle_closure_bias(daily_bars)
    if bias:
        biases.append((bias, reason))
        log.event(1, f"Bias: {bias.upper()} ({reason})",
                  daily_bars[-1]["time"], daily_bars[-1]["close"], "D1")

    # Method 2
    bias, reason = swing_hl_bias(daily_bars)
    if bias:
        biases.append((bias, reason))
        log.event(1, f"Bias: {bias.upper()} ({reason})",
                  daily_bars[-1]["time"], daily_bars[-1]["close"], "D1")

    # Method 3: Discretionary - check if price tapped 1H FVG
    if h1_bars:
        h1_fvgs = detect_fvg(h1_bars)
        if h1_fvgs:
            last_bar = h1_bars[-1]
            for fvg in h1_fvgs:
                if fvg["bottom"] <= last_bar["close"] <= fvg["top"]:
                    bias = "bullish" if last_bar["close"] > fvg["bottom"] else "bearish"
                    biases.append((bias, "Discretionary: tapped 1H FVG"))
                    log.event(1, f"Bias: {bias.upper()} (Tapped 1H FVG)",
                              last_bar["time"], last_bar["close"], "H1")
                    break

    # Method 4
    if m15_bars:
        bias = external_to_internal_bias(m15_bars)
        if bias:
            biases.append((bias, "ExternalToInternal"))
            log.event(1, f"Bias: {bias.upper()} (External->Internal)",
                      m15_bars[-1]["time"], m15_bars[-1]["close"], "M15")

    # ── 1H MSS confirmation ────────────────────────────────────────
    if h1_bars:
        mss_dir = check_1h_mss(h1_bars)
        if mss_dir:
            log.event(2, f"1H MSS Confirms {mss_dir.upper()} Bias",
                      h1_bars[-1]["time"], h1_bars[-1]["close"], "H1")

    # ── Vote on bias direction ──────────────────────────────────────
    if not biases:
        log.event(1, "Bias: NEUTRAL (no method agreed)",
                  daily_bars[-1]["time"], daily_bars[-1]["close"], "D1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        print(f"Done (neutral). Events: {len(log.events)} -> {output}")
        return

    bull_count = sum(1 for b, _ in biases if b == "bullish")
    bear_count = sum(1 for b, _ in biases if b == "bearish")
    final_bias = "bullish" if bull_count >= bear_count else "bearish"

    log.event(3, f"Final Bias: {final_bias.upper()} "
              f"({bull_count} bull, {bear_count} bear votes)",
              daily_bars[-1]["time"], daily_bars[-1]["close"], "D1")

    # ── Optional: Judas Swing entry in bias direction ──────────────
    # After 9:30 AM NY, find 15M unswept levels and trade sweep
    pre_high, pre_low = None, None
    pre_m15 = [b for b in m15_bars
               if get_ny_time(b["time"]).hour < 9]
    if len(pre_m15) >= 3:
        pre_high = max(b["high"] for b in pre_m15[-6:])
        pre_low = min(b["low"] for b in pre_m15[-6:])

        log.event(4, "9:30AM Setup: 15M Pre-Levels",
                  pre_m15[-1]["time"], pre_high, "M15",
                  f"High={pre_high:.2f}, Low={pre_low:.2f}")

        for i in range(0, len(m1_bars)):
            ny = get_ny_time(m1_bars[i]["time"])
            if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
                continue
            if ny.hour >= 11:
                break

            bar = m1_bars[i]

            # Look for sweep in bias direction
            if final_bias == "bullish" and bar["low"] < pre_low:
                log.event(5, "Low Swept (in bias direction)",
                          bar["time"], bar["low"], "M1")

                # MSS check
                seg = m1_bars[max(0, i - 7):i + 1]
                recent_high = max(b["high"] for b in seg[:-1] if b["time"] != bar["time"])
                if bar["close"] > bar["open"] and bar["close"] > recent_high:
                    log.event(6, "MSS + Entry (Long)", bar["time"],
                              bar["close"], "M1")

                    sl = round(bar["low"] * 0.9998, 5)
                    tp = round(pre_high, 5)
                    log.trade("LONG", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"bias": "bullish",
                               "management": "Partial 1:1, BE at 1:1"})
                break

            if final_bias == "bearish" and bar["high"] > pre_high:
                log.event(5, "High Swept (in bias direction)",
                          bar["time"], bar["high"], "M1")

                seg = m1_bars[max(0, i - 7):i + 1]
                recent_low = min(b["low"] for b in seg[:-1] if b["time"] != bar["time"])
                if bar["close"] < bar["open"] and bar["close"] < recent_low:
                    log.event(6, "MSS + Entry (Short)", bar["time"],
                              bar["close"], "M1")

                    sl = round(bar["high"] * 1.0002, 5)
                    tp = round(pre_low, 5)
                    log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"bias": "bearish",
                               "management": "Partial 1:1, BE at 1:1"})
                break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
