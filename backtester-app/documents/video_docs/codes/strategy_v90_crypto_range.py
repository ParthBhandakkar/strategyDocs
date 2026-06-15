"""
Strategy: Crypto Range Strategy (15M+)
Source: Faiz SMC ("How I Make $1,000/Day with ONE Simple Crypto Strategy [100x Trading Tutorial]")
Video: https://www.youtube.com/watch?v=epRYvYzROlA

Core Concept:
  15M+ timeframes for crypto. Define range via push + pullback.
  Sweep of range H/L → MSS + close back inside range → autoblock entry.
  25% partial at 0.5, 50% at 0.79, trail or hold for further targets.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "CryptoRangeStrategy"
SYMBOL = "POPCAT"
TIMEFRAMES = ["M15"]


def find_range(bars: list, lookback: int = 20):
    """Find range via push + pullback (needs MSS to define H/L)."""
    seg = bars[-lookback:]
    if len(seg) < 8:
        return None

    highs = []
    lows = []
    for j in range(1, len(seg) - 1):
        if seg[j]["high"] > seg[j - 1]["high"] and seg[j]["high"] > seg[j + 1]["high"]:
            highs.append((j, seg[j]["high"]))
        if seg[j]["low"] < seg[j - 1]["low"] and seg[j]["low"] < seg[j + 1]["low"]:
            lows.append((j, seg[j]["low"]))

    if not highs or not lows:
        return None

    last_h = max(highs, key=lambda x: x[0])
    last_l = max(lows, key=lambda x: x[0])

    return max(last_h[1], seg[-1]["high"]), min(last_l[1], seg[-1]["low"])


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    if not m15_bars:
        print("No data found")
        return

    # ── Step 1: Identify range ──────────────────────────────────────
    range_info = find_range(m15_bars)
    if range_info is None:
        log.event(1, "No valid range found", m15_bars[-1]["time"], 0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    range_high, range_low = range_info
    log.event(1, "Range Defined", m15_bars[-1]["time"],
              range_high, "M15",
              f"Range High={range_high:.8f}, Range Low={range_low:.8f}")

    # ── Step 2: Sweep → MSS → close inside → entry ─────────────────
    swept = False
    sweep_side = None

    for i in range(3, len(m15_bars)):
        bar = m15_bars[i]

        if not swept:
            if bar["low"] < range_low:
                log.event(2, "Range Low Swept", bar["time"],
                          bar["low"], "M15")
                swept = True
                sweep_side = "long"
                sweep_idx = i
            elif bar["high"] > range_high:
                log.event(2, "Range High Swept", bar["time"],
                          bar["high"], "M15")
                swept = True
                sweep_side = "short"
                sweep_idx = i
            continue

        # MSS + close back inside range
        seg = m15_bars[max(0, i - 5):i + 1]
        if len(seg) < 3:
            continue

        bar_now = m15_bars[i]
        recent_high = max(b["high"] for b in seg[:-1])
        recent_low = min(b["low"] for b in seg[:-1])

        mss_ok = False
        if sweep_side == "long":
            if bar_now["close"] > bar_now["open"] and bar_now["close"] > recent_high:
                mss_ok = True
        else:
            if bar_now["close"] < bar_now["open"] and bar_now["close"] < recent_low:
                mss_ok = True

        if not mss_ok:
            continue

        log.event(3, f"MSS + Range Return ({sweep_side.upper()})",
                  bar_now["time"], bar_now["close"], "M15")

        range_size = range_high - range_low
        fib_05 = range_low + range_size * 0.5
        fib_079 = range_low + range_size * 0.79

        if sweep_side == "long":
            sl = round(range_low * 0.9998, 8)
            tp = round(range_high, 8)
            log.trade("LONG", bar_now["close"], sl, tp, bar_now["time"],
                      symbol, STRATEGY_NAME,
                      {"range_high": range_high, "range_low": range_low,
                       "fib_05": fib_05, "fib_079": fib_079,
                       "management": "25% at 0.5, 50% at 0.79, "
                                     "trail/hold for more"})
        else:
            sl = round(range_high * 1.0002, 8)
            tp = round(range_low, 8)
            log.trade("SHORT", bar_now["close"], sl, tp, bar_now["time"],
                      symbol, STRATEGY_NAME,
                      {"range_high": range_high, "range_low": range_low,
                       "fib_05": range_high - range_size * 0.5,
                       "fib_079": range_high - range_size * 0.79,
                       "management": "25% at 0.5, 50% at 0.79, "
                                     "trail/hold for more"})
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
