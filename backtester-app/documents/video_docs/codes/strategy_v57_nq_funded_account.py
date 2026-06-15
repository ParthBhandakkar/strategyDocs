"""
Strategy: NQ Funded Account Trading Strategy
Source: Faiz SMC ("This Simple NQ Trading Strategy Got Me Funded With $300,000")
Video: https://www.youtube.com/watch?v=rk3Lz5oS8pE

Core Concept:
  HTF FVG on H1/M15/M5. Wait for price to tap it after 9:30 AM NY open.
  Drop to 1M. Identify SMT divergence (NQ vs ES).
  Define dealing range on 1M. Wait for 1M FVG inversion within range.
  Enter immediately on inversion (no retest). V-shaped recovery preferred.
  1:1.5-1:2 target. BE at closest liquidity pool. Partial at 1:1.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "NQFundedAccount"
SYMBOL = "NQ"
TIMEFRAMES = ["M15", "M1"]


def check_smt_divergence(m1_bars: list, idx: int, es_bars: list = None):
    """
    Check SMT divergence at the current bar.
    NQ makes a new low while ES fails = bullish divergence.
    NQ makes a new high while ES fails = bearish divergence.
    """
    if not es_bars or len(es_bars) < 10:
        return None

    nq_recent = m1_bars[max(0, idx - 20):idx + 1]
    nq_low = min(b["low"] for b in nq_recent)
    nq_high = max(b["high"] for b in nq_recent)

    es_recent = es_bars[-min(20, len(es_bars)):]
    es_low = min(b["low"] for b in es_recent)
    es_high = max(b["high"] for b in es_recent)

    bar = m1_bars[idx]

    # Bullish: NQ makes a lower low, ES doesn't
    if nq_low == bar["low"] and nq_low < es_low - 0.5:
        return "bullish"
    # Bearish: NQ makes a higher high, ES doesn't
    if nq_high == bar["high"] and nq_high > es_high + 0.5:
        return "bearish"

    return None


def find_inversion(bars: list, idx: int, direction: str):
    """
    Find 1M FVG inversion within dealing range.
    Returns (fvg_dict) or None.
    """
    seg = bars[max(0, idx - 10):idx + 1]
    fvgs = detect_fvg(seg)
    bar = bars[idx]

    for f in fvgs:
        if direction == "bullish":
            if f["direction"] == "bullish" and bar["close"] > f["top"] and bar["close"] > bar["open"]:
                return f
        else:
            if f["direction"] == "bearish" and bar["close"] < f["bottom"] and bar["close"] < bar["open"]:
                return f
    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")
    es_m1_bars = get_bars(data_dir, "ES", "M1")

    if not m15_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: HTF FVG ─────────────────────────────────────────────
    m15_fvgs = detect_fvg(m15_bars)
    if not m15_fvgs:
        log.event(1, "No HTF (15M) FVG Found", m15_bars[-1]["time"], 0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, "HTF FVG Levels (15M)", m15_bars[-1]["time"], 0, "M15",
              f"Count: {len(m15_fvgs)}")

    # ── Step 2-3: Post-9:30 entry ───────────────────────────────────
    m1_start = next(
        (i for i, b in enumerate(m1_bars)
         if get_ny_time(b["time"]).hour >= 9 and get_ny_time(b["time"]).minute >= 30), 0
    )

    trade_taken = False
    has_tapped_fvg = False

    for i in range(m1_start + 3, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])

        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11 and ny.minute > 30:
            break
        if trade_taken:
            break

        # ── Price taps HTF FVG ──────────────────────────────────────
        in_fvg = False
        relevant_fvg = None
        for fvg in m15_fvgs:
            if fvg["bottom"] <= bar["low"] <= fvg["top"] or fvg["bottom"] <= bar["high"] <= fvg["top"]:
                in_fvg = True
                relevant_fvg = fvg
                break

        if not in_fvg:
            continue

        if not has_tapped_fvg:
            has_tapped_fvg = True
            log.event(2, "Price Tapped 15M FVG", bar["time"],
                      bar["close"], "M1",
                      f"FVG: {relevant_fvg['top']:.2f} - {relevant_fvg['bottom']:.2f}")

        # ── SMT divergence ──────────────────────────────────────────
        smt_dir = check_smt_divergence(m1_bars, i, es_m1_bars)
        if smt_dir is None:
            continue

        log.event(3, f"SMT Divergence ({smt_dir.upper()})", bar["time"],
                  bar["close"], "M1",
                  "NQ vs ES confirmed")

        # ── 1M FVG inversion entry ──────────────────────────────────
        inv_fvg = find_inversion(m1_bars, i, smt_dir)
        if inv_fvg is None:
            continue

        log.event(4, f"1M FVG Inversion ({smt_dir.upper()})",
                  bar["time"], bar["close"], "M1",
                  f"FVG: {inv_fvg['top']:.2f}-{inv_fvg['bottom']:.2f}")

        if smt_dir == "bullish":
            sl = round(bar["low"] * 0.9998, 5)
            # 1:1.5 target
            tp = round(bar["close"] + (bar["close"] - sl) * 1.5, 5)
            log.trade("LONG", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"15m_fvg_top": relevant_fvg["top"],
                       "15m_fvg_bottom": relevant_fvg["bottom"],
                       "smt": "NQ/ES divergence",
                       "ifvg_top": inv_fvg["top"],
                       "ifvg_bottom": inv_fvg["bottom"],
                       "management": "Partial at 1:1, BE at closest liquidity pool"})
        else:
            sl = round(bar["high"] * 1.0002, 5)
            tp = round(bar["close"] - (sl - bar["close"]) * 1.5, 5)
            log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"15m_fvg_top": relevant_fvg["top"],
                       "15m_fvg_bottom": relevant_fvg["bottom"],
                       "smt": "NQ/ES divergence",
                       "ifvg_top": inv_fvg["top"],
                       "ifvg_bottom": inv_fvg["bottom"],
                       "management": "Partial at 1:1, BE at closest liquidity pool"})

        trade_taken = True
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
