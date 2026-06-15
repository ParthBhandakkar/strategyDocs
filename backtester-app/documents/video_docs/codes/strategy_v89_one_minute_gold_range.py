"""
Strategy: 1-Minute Gold Range Trading (0.5 Retracement)
Source: Faiz SMC ("Easy ICT 1 Minute Gold Trading Strategy That Works! (Insane Accuracy)")
Video: https://www.youtube.com/watch?v=IXW4lpfiknQ

Core Concept:
  1M Gold (or indices). Define range: push + pullback that retraces
  0.5 (50%) to validate. Wait for sweep of range H/L.
  1M MSS + close back inside range. Entry from autoblock.
  25% partial at 0.5, 50% at 0.79, trail to opposite end.
  Trade only during active sessions.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "OneMinuteGoldRange"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M1"]


def find_valid_range(bars: list, idx: int, lookback: int = 15):
    """
    Find a range defined by push + pullback that retraces >= 0.5.
    Returns (range_high, range_low) or None.
    """
    seg = bars[max(0, idx - lookback):idx + 1]
    if len(seg) < 6:
        return None

    # Find the most recent swing high and low
    highs = []
    lows = []
    for j in range(1, len(seg) - 1):
        if seg[j]["high"] > seg[j - 1]["high"] and seg[j]["high"] > seg[j + 1]["high"]:
            highs.append((j, seg[j]["high"]))
        if seg[j]["low"] < seg[j - 1]["low"] and seg[j]["low"] < seg[j + 1]["low"]:
            lows.append((j, seg[j]["low"]))

    if not highs or not lows:
        return None

    # Find the most recent pair (high after low, or low after high)
    last_h = max(highs, key=lambda x: x[0])
    last_l = max(lows, key=lambda x: x[0])

    if last_h[0] > last_l[0]:
        range_high = last_h[1]
        range_low = last_l[1]
    else:
        range_high = last_h[1]
        range_low = last_l[1]

    # Check 0.5 retracement validation
    range_size = range_high - range_low
    if range_size <= 0:
        return None

    # The pullback should reach at least 0.5 of the range
    if last_h[0] > last_l[0]:
        pullback_idx = last_h[0]
        pullback_low = min(b["low"] for b in seg[last_l[0]:last_h[0] + 1])
        retrace = (range_high - pullback_low) / range_size
        if retrace < 0.5:
            return None
    else:
        pullback_idx = last_l[0]
        pullback_high = max(b["high"] for b in seg[last_h[0]:last_l[0] + 1])
        retrace = (pullback_high - range_low) / range_size
        if retrace < 0.5:
            return None

    return range_high, range_low


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m1_bars = get_bars(data_dir, symbol, "M1")
    if not m1_bars:
        print("No data found")
        return

    # ── Find valid range ────────────────────────────────────────────
    range_info = find_valid_range(m1_bars, len(m1_bars) - 1)
    if range_info is None:
        log.event(1, "No valid range found (need 0.5 retracement)",
                  m1_bars[-1]["time"], 0, "M1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    range_high, range_low = range_info
    log.event(1, "Valid Range Defined", m1_bars[-1]["time"],
              range_high, "M1",
              f"Range High={range_high:.2f}, Range Low={range_low:.2f}")

    # ── Wait for sweep → MSS → close back inside → entry ───────────
    swept = False
    sweep_side = None

    for i in range(5, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])

        # Active sessions only
        if ny.hour < 1 or 2 <= ny.hour < 8:
            pass
        if ny.hour >= 17:
            continue

        if not swept:
            if bar["low"] < range_low:
                log.event(2, "Range Low Swept", bar["time"],
                          bar["low"], "M1")
                swept = True
                sweep_side = "bullish"
                sweep_idx = i
            elif bar["high"] > range_high:
                log.event(2, "Range High Swept", bar["time"],
                          bar["high"], "M1")
                swept = True
                sweep_side = "bearish"
                sweep_idx = i
            continue

        # MSS + close back inside range
        seg = m1_bars[max(0, i - 7):i + 1]
        if len(seg) < 4:
            continue

        bar_now = m1_bars[i]
        recent_high = max(b["high"] for b in seg[:-1])
        recent_low = min(b["low"] for b in seg[:-1])

        mss_ok = False
        if sweep_side == "bullish":
            if bar_now["close"] > bar_now["open"] and bar_now["close"] > recent_high \
               and bar_now["close"] > range_low:
                mss_ok = True
        else:
            if bar_now["close"] < bar_now["open"] and bar_now["close"] < recent_low \
               and bar_now["close"] < range_high:
                mss_ok = True

        if not mss_ok:
            continue

        log.event(3, f"MSS + Close Inside Range ({sweep_side.upper()})",
                  bar_now["time"], bar_now["close"], "M1")

        # Fib-based TP levels
        range_size = range_high - range_low
        fib_05 = range_low + range_size * 0.5
        fib_079 = range_low + range_size * 0.79

        if sweep_side == "bullish":
            sl = round(range_low * 0.9998, 5)
            tp = round(range_high, 5)
            log.trade("LONG", bar_now["close"], sl, tp, bar_now["time"],
                      symbol, STRATEGY_NAME,
                      {"range_high": range_high, "range_low": range_low,
                       "fib_05": fib_05, "fib_079": fib_079,
                       "management": "25% at 0.5, 50% at 0.79, "
                                     "trail to opposite end"})
        else:
            sl = round(range_high * 1.0002, 5)
            tp = round(range_low, 5)
            log.trade("SHORT", bar_now["close"], sl, tp, bar_now["time"],
                      symbol, STRATEGY_NAME,
                      {"range_high": range_high, "range_low": range_low,
                       "fib_05": range_high - range_size * 0.5,
                       "fib_079": range_high - range_size * 0.79,
                       "management": "25% at 0.5, 50% at 0.79, "
                                     "trail to opposite end"})
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
