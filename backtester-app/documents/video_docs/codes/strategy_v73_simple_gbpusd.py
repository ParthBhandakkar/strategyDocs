"""
Strategy: Simple Trading Strategy for GBPUSD (4H + SMT + Sweep)
Source: Faiz SMC ("This boring trading strategy made me $6,620 in a few minutes..")
Video: https://www.youtube.com/watch?v=LPmmymPRpno

Core Concept:
  GBPUSD. 4H order flow (direction). Identify 4H PD arrays (OB/FVG).
  Wait for price to tap PD array. 15M SMT divergence with correlated
  pair (EURUSD). Trade the stronger pair (one that didn't make HH/LL).
  Sweep of short-term liquidity → close above/below sweep candle body
  → entry on OB retest. 1:2 target.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "SimpleGBPUSD"
SYMBOL = "GBPUSD"
TIMEFRAMES = ["H4", "M15", "M5"]


def find_4h_orderflow(bars_h4: list):
    """Identify 4H direction."""
    if len(bars_h4) < 6:
        return None
    recent = bars_h4[-6:]
    highs = [b["high"] for b in recent]
    lows = [b["low"] for b in recent]
    if highs[-1] > highs[-2] > highs[-3] and lows[-1] > lows[-2]:
        return "bullish"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2] < lows[-3]:
        return "bearish"
    return None


def find_4h_pd_arrays(bars_h4: list):
    """Find 4H PD arrays (OB + FVG)."""
    elements = []

    # FVGs
    fvgs = detect_fvg(bars_h4)
    for f in fvgs:
        elements.append(("FVG", f["top"], f["bottom"], None))

    # Order blocks (simplified)
    for j in range(1, len(bars_h4) - 1):
        if bars_h4[j]["close"] > bars_h4[j]["open"]:
            if bars_h4[j - 1]["close"] < bars_h4[j - 1]["open"]:
                elements.append(("OB", bars_h4[j - 1]["high"],
                                 bars_h4[j - 1]["low"], None))
        if bars_h4[j]["close"] < bars_h4[j]["open"]:
            if bars_h4[j - 1]["close"] > bars_h4[j - 1]["open"]:
                elements.append(("OB", bars_h4[j - 1]["low"],
                                 bars_h4[j - 1]["high"], None))

    return elements


def check_15m_smt_divergence(bars_pri: list, bars_corr: list, idx: int):
    """SMT: primary vs correlated on 15M. Returns direction + which is stronger."""
    if not bars_corr or len(bars_corr) < 8:
        return None, None

    pri_seg = bars_pri[max(0, idx - 8):idx + 1]
    corr_seg = bars_corr[-8:]

    pri_low = min(b["low"] for b in pri_seg)
    pri_high = max(b["high"] for b in pri_seg)
    corr_low = min(b["low"] for b in corr_seg)
    corr_high = max(b["high"] for b in corr_seg)

    bar = bars_pri[idx]

    # Bearish divergence: priority makes HH, correlated doesn't
    if bar["high"] == pri_high and bar["high"] > pri_seg[-2]["high"] \
       and corr_high <= corr_seg[-2]["high"]:
        return "bearish", "primary"  # primary is weaker = SELL primary
    # Bullish divergence: primary makes LL, correlated doesn't
    if bar["low"] == pri_low and bar["low"] < pri_seg[-2]["low"] \
       and corr_low >= corr_seg[-2]["low"]:
        return "bullish", "primary"  # primary is weaker = BUY primary

    return None, None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "H4")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m5_bars = get_bars(data_dir, symbol, "M5")
    eur_m15_bars = get_bars(data_dir, "EURUSD", "M15")

    if not h4_bars or not m15_bars:
        print("No data found")
        return

    # ── Step 1: 4H order flow ───────────────────────────────────────
    direction = find_4h_orderflow(h4_bars)
    if direction is None:
        log.event(1, "No clear 4H direction", h4_bars[-1]["time"],
                  h4_bars[-1]["close"], "H4", "Switching pair")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"4H Order Flow: {direction.upper()}",
              h4_bars[-1]["time"], h4_bars[-1]["close"], "H4")

    # ── Step 2: 4H PD arrays ────────────────────────────────────────
    pd_arrays = find_4h_pd_arrays(h4_bars)
    if not pd_arrays:
        log.event(2, "No 4H PD arrays found", h4_bars[-1]["time"], 0, "H4")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(2, f"4H PD Arrays: {len(pd_arrays)} found",
              h4_bars[-1]["time"], 0, "H4")

    # ── Step 3-4: 15M scan for setup ────────────────────────────────
    tapped_pd = False
    found_trade = False

    for i in range(5, len(m15_bars)):
        bar = m15_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 8 or ny.hour > 16:
            continue
        if found_trade:
            break

        # ── Price taps 4H PD array ─────────────────────────────
        if not tapped_pd:
            for pd_type, pd_top, pd_bottom, _ in pd_arrays:
                if pd_bottom <= bar["low"] <= pd_top \
                   or pd_bottom <= bar["high"] <= pd_top:
                    tapped_pd = True
                    log.event(3, f"Price Tapped 4H {pd_type}",
                              bar["time"], bar["close"], "M15",
                              f"Top={pd_top:.5f}, Bottom={pd_bottom:.5f}")
                    break
            continue

        # ── SMT divergence ────────────────────────────────────
        smt_dir, stronger = check_15m_smt_divergence(
            m15_bars, eur_m15_bars, i
        )
        if smt_dir is None:
            continue

        log.event(4, f"15M SMT Divergence ({smt_dir.upper()})",
                  bar["time"], bar["close"], "M15",
                  f"Stronger: {symbol if stronger == 'correlated' else symbol}")

        # ── Liquidity sweep + close above/below body ──────────
        # Check for sweep in the direction suggested by SMT
        if smt_dir == "bullish":
            # Look for sweep of a recent low
            recent_low = min(
                b["low"] for b in m15_bars[max(0, i - 5):i]
            )
            if bar["low"] < recent_low and bar["close"] > bar["open"]:
                # Entry on retest of the sweep candle's body
                log.event(5, "Liquidity Sweep + Close Above Body (Long)",
                          bar["time"], bar["close"], "M15")

                sl = round(bar["low"] * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"4h_direction": direction,
                           "smt_div": "confirmed",
                           "stronger_pair": symbol,
                           "management": "1:2 RR"})
                found_trade = True
                break
        else:
            recent_high = max(
                b["high"] for b in m15_bars[max(0, i - 5):i]
            )
            if bar["high"] > recent_high and bar["close"] < bar["open"]:
                log.event(5, "Liquidity Sweep + Close Below Body (Short)",
                          bar["time"], bar["close"], "M15")

                sl = round(bar["high"] * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"4h_direction": direction,
                           "smt_div": "confirmed",
                           "stronger_pair": symbol,
                           "management": "1:2 RR"})
                found_trade = True
                break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
