"""
Strategy: Trend Continuation "Continuation Purge" Entry Model
Source: Faiz SMC ("This entry model will change how you trade forever.. (20x results)")
Video: https://www.youtube.com/watch?v=k76AXYhcr1U

Core Concept:
  Trend continuation only. In a clear trend, identify the last BOS
  high (bearish) or low (bullish). Wait for price to sweep that level.
  Within the dealing range, wait for FVG inversion.
  Enter on close above/below the FVG. 30-40% partial at 1:1, BE at
  1:1, final TP at next major H/L. Use SMT divergence for confirmation.
  Invalid if closest liquidity pool hit before entry.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "ContinuationPurge"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M5", "M1"]


def detect_trend(bars: list, idx: int, lookback: int = 24):
    """
    Determine trend direction. Returns 'bullish', 'bearish', or None.
    Uses swing highs/lows.
    """
    seg = bars[max(0, idx - lookback):idx + 1]
    if len(seg) < 8:
        return None

    highs = []
    lows = []
    for j in range(1, len(seg) - 1):
        if seg[j]["high"] > seg[j - 1]["high"] and seg[j]["high"] > seg[j + 1]["high"]:
            highs.append(seg[j]["high"])
        if seg[j]["low"] < seg[j - 1]["low"] and seg[j]["low"] < seg[j + 1]["low"]:
            lows.append(seg[j]["low"])

    if len(highs) < 2 or len(lows) < 2:
        return None

    # Bullish: higher highs and higher lows
    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "bullish"
    # Bearish: lower highs and lower lows
    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "bearish"

    return None


def find_last_bos_level(bars: list, idx: int, trend: str,
                        lookback: int = 30):
    """
    Find the high (bearish trend) or low (bullish trend) that caused
    the most recent break of structure.
    """
    seg = bars[max(0, idx - lookback):idx + 1]
    if len(seg) < 6:
        return None, None

    if trend == "bullish":
        # Find a swing low that was broken by subsequent price action
        lows = []
        for j in range(1, len(seg) - 1):
            if seg[j]["low"] < seg[j - 1]["low"] and seg[j]["low"] < seg[j + 1]["low"]:
                lows.append((j, seg[j]["low"]))

        if not lows:
            return None, None

        # The most recent swing low
        last_low_idx, last_low = max(lows, key=lambda x: x[0])
        # Check if this low was actually swept (price went below it)
        for j in range(last_low_idx, len(seg)):
            if seg[j]["low"] < last_low:
                return last_low, seg[last_low_idx]["time"]
        return None, None

    # Bearish
    highs = []
    for j in range(1, len(seg) - 1):
        if seg[j]["high"] > seg[j - 1]["high"] and seg[j]["high"] > seg[j + 1]["high"]:
            highs.append((j, seg[j]["high"]))

    if not highs:
        return None, None

    last_high_idx, last_high = max(highs, key=lambda x: x[0])
    for j in range(last_high_idx, len(seg)):
        if seg[j]["high"] > last_high:
            return last_high, seg[last_high_idx]["time"]
    return None, None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m5_bars = get_bars(data_dir, symbol, "M5")
    if not m5_bars:
        print("No data found")
        return

    trend = None
    bos_level = None
    bos_time = None
    state = "FIND_TREND"

    for i in range(30, len(m5_bars)):
        bar = m5_bars[i]
        ny = get_ny_time(bar["time"])

        # Kill zone check for timeframes below 4H
        if ny.hour < 8 or ny.hour >= 16:
            continue

        # ── State: FIND_TREND ───────────────────────────────────────
        if state == "FIND_TREND":
            trend = detect_trend(m5_bars, i)
            if trend is None:
                continue

            log.event(1, f"Trend: {trend.upper()}", bar["time"],
                      bar["close"], "M5")

            result = find_last_bos_level(m5_bars, i, trend)
            if result[0] is None:
                state = "FIND_TREND"
                continue

            bos_level, bos_time = result
            state = "WAIT_SWEEP"

            log.event(2, f"BOS Level Identified ({trend.upper()})",
                      bos_time or bar["time"],
                      bos_level, "M5",
                      f"Level: {bos_level:.2f}")

        # ── State: WAIT_SWEEP ───────────────────────────────────────
        elif state == "WAIT_SWEEP":
            if trend == "bullish" and bar["low"] < bos_level:
                log.event(3, "BOS Low Swept", bar["time"],
                          bar["low"], "M5")
                state = "WAIT_INVERSION"
                sweep_idx = i
            elif trend == "bearish" and bar["high"] > bos_level:
                log.event(3, "BOS High Swept", bar["time"],
                          bar["high"], "M5")
                state = "WAIT_INVERSION"
                sweep_idx = i

        # ── State: WAIT_INVERSION ───────────────────────────────────
        elif state == "WAIT_INVERSION":
            # Find FVGs since the sweep
            fvgs = detect_fvg(
                m5_bars[max(0, sweep_idx):i + 1]
            )

            if not fvgs:
                continue

            for fvg in fvgs:
                if trend == "bullish" and bar["close"] > fvg["top"]:
                    log.event(4, "FVG Inversion (Long)", bar["time"],
                              bar["close"], "M5",
                              f"FVG: {fvg['top']:.2f}-{fvg['bottom']:.2f}")

                    sl = round(bar["low"] * 0.9998, 5)
                    # Target next major high
                    recent_high = max(
                        b["high"] for b in
                        m5_bars[max(0, i - 20):i + 1]
                    )
                    tp = round(recent_high + (recent_high - bar["low"]) * 0.5, 5)

                    log.trade("LONG", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"trend": "bullish",
                               "bos_level": bos_level,
                               "fvg_top": fvg["top"],
                               "fvg_bottom": fvg["bottom"],
                               "management": "30-40% partial at 1:1, "
                                             "BE at 1:1, TP next major H/L"})
                    state = "FIND_TREND"
                    break

                if trend == "bearish" and bar["close"] < fvg["bottom"]:
                    log.event(4, "FVG Inversion (Short)", bar["time"],
                              bar["close"], "M5",
                              f"FVG: {fvg['top']:.2f}-{fvg['bottom']:.2f}")

                    sl = round(bar["high"] * 1.0002, 5)
                    recent_low = min(
                        b["low"] for b in
                        m5_bars[max(0, i - 20):i + 1]
                    )
                    tp = round(recent_low - (bar["high"] - recent_low) * 0.5, 5)

                    log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"trend": "bearish",
                               "bos_level": bos_level,
                               "fvg_top": fvg["top"],
                               "fvg_bottom": fvg["bottom"],
                               "management": "30-40% partial at 1:1, "
                                             "BE at 1:1, TP next major H/L"})
                    state = "FIND_TREND"
                    break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
