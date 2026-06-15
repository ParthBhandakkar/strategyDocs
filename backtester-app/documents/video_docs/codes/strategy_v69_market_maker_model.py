"""
Strategy: ICT Market Maker Model (MMXM)
Source: Faiz SMC ("Make 'F*ck You' Money With This Simple ICT MMXM Strategy")
Video: https://www.youtube.com/watch?v=06DxvYmOXP4

Core Concept:
  4H order flow (trend). Identify lowest (bullish) or highest (bearish)
  point before BOS. Wait for sweep of that level.
  15M MSS with strong displacement. Entry on retest of FVG or breaker
  block formed during shift. SL above/below autoblock.
  Target the original consolidation zone. Trade London/NY killzone.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "MarketMakerModel"
SYMBOL = "NZDUSD"
TIMEFRAMES = ["H4", "M15", "M5"]


def detect_4h_trend(bars_h4: list):
    """Identify main trend on 4H."""
    if len(bars_h4) < 8:
        return None

    recent = bars_h4[-8:]
    highs = [b["high"] for b in recent]
    lows = [b["low"] for b in recent]

    if highs[-1] > highs[-2] > highs[-3] and lows[-1] > lows[-2] > lows[-3]:
        return "bullish"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2] < lows[-3]:
        return "bearish"

    return None


def find_pre_bos_liquidity(bars: list, trend: str, lookback: int = 30):
    """
    Find the low (bullish) or high (bearish) before the most recent
    break of structure on the H4 chart.
    """
    seg = bars[-lookback:]
    if len(seg) < 6:
        return None, None

    if trend == "bullish":
        # Find the last swing low before BOS
        lows = []
        for j in range(1, len(seg) - 1):
            if seg[j]["low"] < seg[j - 1]["low"] and seg[j]["low"] < seg[j + 1]["low"]:
                lows.append((j, seg[j]["low"]))
        if not lows:
            return None, None
        last_low_idx, last_low = max(lows, key=lambda x: x[0])
        return last_low, seg[last_low_idx]["time"]
    else:
        highs = []
        for j in range(1, len(seg) - 1):
            if seg[j]["high"] > seg[j - 1]["high"] and seg[j]["high"] > seg[j + 1]["high"]:
                highs.append((j, seg[j]["high"]))
        if not highs:
            return None, None
        last_high_idx, last_high = max(highs, key=lambda x: x[0])
        return last_high, seg[last_high_idx]["time"]


def check_mss_displacement(bars: list, idx: int, direction: str):
    """Check 15M MSS with strong displacement."""
    seg = bars[max(0, idx - 6):idx + 1]
    if len(seg) < 3:
        return False

    bar = bars[idx]
    recent_high = max(b["high"] for b in seg[:-1])
    recent_low = min(b["low"] for b in seg[:-1])

    if direction == "bullish":
        if bar["close"] > bar["open"] and bar["close"] > recent_high:
            for k in range(1, len(seg) - 1):
                if seg[k]["low"] > seg[k - 1]["high"]:
                    return True
    else:
        if bar["close"] < bar["open"] and bar["close"] < recent_low:
            for k in range(1, len(seg) - 1):
                if seg[k]["high"] < seg[k - 1]["low"]:
                    return True

    return False


def find_entry_fvg(bars: list, idx: int, direction: str):
    """Find FVG/breaker block within the MSS move for retest entry."""
    seg = bars[max(0, idx - 8):idx + 1]
    fvgs = detect_fvg(seg)
    if not fvgs:
        return None

    # Return the most recent FVG that aligns with direction
    for fvg in reversed(fvgs):
        if direction == "bullish" and fvg["direction"] == "bullish":
            return fvg
        if direction == "bearish" and fvg["direction"] == "bearish":
            return fvg
    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "H4")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m5_bars = get_bars(data_dir, symbol, "M5")

    if not h4_bars or not m15_bars:
        print("No data found")
        return

    # ── Step 1: 4H trend ───────────────────────────────────────────
    trend = detect_4h_trend(h4_bars)
    if trend is None:
        log.event(1, "No clear 4H trend", h4_bars[-1]["time"],
                  h4_bars[-1]["close"], "H4")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"4H Trend: {trend.upper()}", h4_bars[-1]["time"],
              h4_bars[-1]["close"], "H4")

    # ── Step 2: Pre-BOS liquidity ──────────────────────────────────
    liq_level, liq_time = find_pre_bos_liquidity(h4_bars, trend)
    if liq_level is None:
        log.event(2, "No pre-BOS liquidity found", h4_bars[-1]["time"], 0, "H4")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(2, f"Pre-BOS Liquidity: {liq_level:.2f}",
              liq_time or h4_bars[-1]["time"],
              liq_level, "H4", f"Direction: {trend.upper()}")

    # ── Step 3-4: Scan 15M for sweep → MSS → entry ─────────────────
    swept = False
    found_trade = False

    for i in range(5, len(m15_bars)):
        bar = m15_bars[i]
        ny = get_ny_time(bar["time"])

        # London/NY killzone
        if ny.hour < 3 or (8 <= ny.hour < 17):
            pass
        if ny.hour < 3 and ny.hour >= 0:
            continue
        if 3 <= ny.hour < 8:
            pass
        if ny.hour >= 17:
            continue
        if found_trade:
            break

        # ── Sweep ──────────────────────────────────────────────
        if not swept:
            if trend == "bullish" and bar["low"] < liq_level:
                log.event(3, "15M: Liquidity Sweep (Low)",
                          bar["time"], bar["low"], "M15")
                swept = True
                sweep_idx = i
            elif trend == "bearish" and bar["high"] > liq_level:
                log.event(3, "15M: Liquidity Sweep (High)",
                          bar["time"], bar["high"], "M15")
                swept = True
                sweep_idx = i
            continue

        # ── MSS with displacement ─────────────────────────────
        if not check_mss_displacement(m15_bars, i, trend):
            continue

        log.event(4, f"15M MSS with Displacement ({trend.upper()})",
                  bar["time"], bar["close"], "M15")

        # ── Entry on FVG retest ───────────────────────────────
        entry_fvg = find_entry_fvg(m15_bars, i, trend)
        if entry_fvg is None:
            continue

        log.event(5, f"Entry on FVG Retest ({trend.upper()})",
                  bar["time"], bar["close"], "M15",
                  f"FVG: {entry_fvg['top']:.2f}-{entry_fvg['bottom']:.2f}")

        if trend == "bullish":
            sl = round(bar["low"] * 0.9998, 5)
            tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
            log.trade("LONG", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"4h_trend": "bullish",
                       "swept_level": liq_level,
                       "fvg_top": entry_fvg["top"],
                       "fvg_bottom": entry_fvg["bottom"],
                       "management": "SL above/below autoblock, "
                                     "TP at original consolidation"})
        else:
            sl = round(bar["high"] * 1.0002, 5)
            tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
            log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"4h_trend": "bearish",
                       "swept_level": liq_level,
                       "fvg_top": entry_fvg["top"],
                       "fvg_bottom": entry_fvg["bottom"],
                       "management": "SL above/below autoblock, "
                                     "TP at original consolidation"})

        found_trade = True
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
