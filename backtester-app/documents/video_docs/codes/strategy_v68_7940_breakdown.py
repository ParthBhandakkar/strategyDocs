"""
Strategy: $7,940 Trade Breakdown (GBPUSD SMT + CSOD)
Source: Faiz SMC ("I Made $7,940 Today Using This Boring ICT Trading Strategy..")
Video: https://www.youtube.com/watch?v=l_hlLfj2UFs

Core Concept:
  GBPUSD. 1H order flow → 1H FVG aligned with trend.
  Wait for price to tap 1H FVG. 15M SMT divergence (GBPUSD/EURUSD).
  CSOD entry: candle sweeps liquidity low, wait for close above body.
  Entry on autoblock retest. 1:2 target, SL below autoblock low.
  No consolidation on HTF.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "SevenNineFourZeroBreakdown"
SYMBOL = "GBPUSD"
TIMEFRAMES = ["H1", "M15", "M5"]


def check_1h_order_flow(bars_h1: list):
    """Check if 1H order flow is clean: consistent direction."""
    if len(bars_h1) < 6:
        return None

    recent = bars_h1[-6:]
    highs = [b["high"] for b in recent]
    lows = [b["low"] for b in recent]

    if highs[-1] > highs[-2] > highs[-3] and lows[-1] > lows[-2]:
        return "bullish"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2] < lows[-3]:
        return "bearish"

    return None


def check_smt_divergence(bars_pri: list, bars_corr: list, idx: int):
    """Check SMT divergence on 15M between GBPUSD and EURUSD."""
    if not bars_corr or len(bars_corr) < 8:
        return None

    pri_seg = bars_pri[max(0, idx - 8):idx + 1]
    corr_seg = bars_corr[-8:]

    bar = bars_pri[idx]
    pri_low = min(b["low"] for b in pri_seg)
    pri_high = max(b["high"] for b in pri_seg)
    corr_low = min(b["low"] for b in corr_seg)
    corr_high = max(b["high"] for b in corr_seg)

    if bar["low"] == pri_low and bar["low"] < pri_seg[-2]["low"] \
       and corr_low >= corr_seg[-2]["low"]:
        return "bullish"
    if bar["high"] == pri_high and bar["high"] > pri_seg[-2]["high"] \
       and corr_high <= corr_seg[-2]["high"]:
        return "bearish"

    return None


def detect_csod(bars: list, idx: int):
    """
    Change in State of Delivery: candle sweeps a liquidity low,
    then subsequent candle closes above that candle's body.
    """
    if idx < 2 or idx >= len(bars):
        return False

    sweep_candle = bars[idx - 1]
    confirm_candle = bars[idx]

    # Sweep candle: makes a lower low than any in recent lookback
    lookback = max(0, idx - 5)
    recent_low = min(b["low"] for b in bars[lookback:idx])

    if sweep_candle["low"] < recent_low \
       and confirm_candle["close"] > sweep_candle["high"]:
        return True

    return False


def find_autoblock(bars: list, idx: int):
    """Find autoblock (single candle) for retest entry."""
    if idx < 1 or idx >= len(bars):
        return None

    bar = bars[idx]
    return {"high": bar["high"], "low": bar["low"],
            "time": bar["time"]}


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m5_bars = get_bars(data_dir, symbol, "M5")
    eur_m15_bars = get_bars(data_dir, "EURUSD", "M15")

    if not h1_bars or not m15_bars:
        print("No data found")
        return

    # ── Step 1: 1H order flow ───────────────────────────────────────
    of_dir = check_1h_order_flow(h1_bars)
    if of_dir is None:
        log.event(1, "No clear 1H order flow (consolidation?)",
                  h1_bars[-1]["time"], h1_bars[-1]["close"], "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"1H Order Flow: {of_dir.upper()}",
              h1_bars[-1]["time"], h1_bars[-1]["close"], "H1")

    # ── Step 2: 1H FVG ─────────────────────────────────────────────
    h1_fvgs = detect_fvg(h1_bars)

    if not h1_fvgs:
        log.event(2, "No 1H FVG Found", h1_bars[-1]["time"], 0, "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(2, "1H FVG Levels", h1_bars[-1]["time"], 0, "H1",
              f"Count: {len(h1_fvgs)}")

    # ── Step 3-5: 15M SMT + CSOD + entry ───────────────────────────
    found_entry = False
    has_tapped_fvg = False

    for i in range(3, len(m15_bars)):
        bar = m15_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 8 or ny.hour > 16:
            continue

        # ── Price taps 1H FVG ──────────────────────────────────
        if not has_tapped_fvg:
            for fvg in h1_fvgs:
                if fvg["bottom"] <= bar["low"] <= fvg["top"] \
                   or fvg["bottom"] <= bar["high"] <= fvg["top"]:
                    has_tapped_fvg = True
                    log.event(3, "Price Tapped 1H FVG", bar["time"],
                              bar["close"], "M15",
                              f"FVG: {fvg['top']:.2f}-{fvg['bottom']:.2f}")
                    break

        if not has_tapped_fvg:
            continue

        # ── SMT divergence ─────────────────────────────────────
        smt_dir = check_smt_divergence(m15_bars, eur_m15_bars, i)
        if smt_dir is None:
            continue

        log.event(4, f"15M SMT Divergence ({smt_dir.upper()})",
                  bar["time"], bar["close"], "M15",
                  "GBPUSD/EURUSD")

        # ── CSOD ───────────────────────────────────────────────
        if not detect_csod(m15_bars, i):
            continue

        log.event(5, "CSOD Confirmed (sweep + close above body)",
                  bar["time"], bar["close"], "M15")

        # ── Entry: retest of autoblock ─────────────────────────
        autoblock = find_autoblock(m15_bars, i)
        if autoblock is None:
            continue

        log.event(6, f"Entry: Retest of Autoblock ({smt_dir.upper()})",
                  bar["time"], bar["close"], "M15")

        if smt_dir == "bullish":
            sl = round(autoblock["low"] * 0.9998, 5)
            tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
            log.trade("LONG", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"setup": "SMT+CSOD+Autoblock",
                       "1h_order_flow": of_dir,
                       "smt_pair": "EURUSD",
                       "management": "1:2 RR, SL below autoblock low"})
        else:
            sl = round(autoblock["high"] * 1.0002, 5)
            tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
            log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"setup": "SMT+CSOD+Autoblock",
                       "1h_order_flow": of_dir,
                       "smt_pair": "EURUSD",
                       "management": "1:2 RR, SL above autoblock high"})

        found_entry = True
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
