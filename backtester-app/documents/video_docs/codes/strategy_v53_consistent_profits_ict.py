"""
Strategy: ICT Trading Strategy for Consistent Profits
Source: Faiz SMC ("This Stupid ICT Trading Strategy Makes $1,000 Everyday!")
Video: http://www.youtube.com/watch?v=VOs4Dztopyo

Core Concept:
  Pre-9:30 15M FVG. Price taps into 15M FVG post-9:30.
  1M SMT divergence (NQ vs ES) + W-shape inversion (sharp V/W recovery).
  Enter on candle close inverting the 1M FVG. 30% partial at 0.7 RR.
  SL below candle body. BE at first fractal liquidity level.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "ConsistentProfitsICT"
SYMBOL = "MNQ"
TIMEFRAMES = ["M15", "M1"]


def detect_w_shape_inversion(bars: list, bar_idx: int, direction: str) -> bool:
    """
    Check for a sharp V or W-shaped recovery after a sweep.
    Look for: recent sweep of a low/high followed by an immediate
    reversal with minimal consolidation bars.
    """
    seg = bars[max(0, bar_idx - 8):bar_idx + 1]
    if len(seg) < 3:
        return False

    if direction == "bullish":
        # Find the lowest point in the segment
        low_point = min(b["low"] for b in seg)
        low_idx = next(i for i, b in enumerate(seg) if b["low"] == low_point)

        if low_idx < 1 or low_idx >= len(seg) - 1:
            return False

        # Check for sharp reversal: few bars between low and break above
        # Also check displacement: bar closes with strength
        after = seg[low_idx + 1:]
        if len(after) < 1:
            return False

        # W-shape: bar closes above a prior swing level
        recent_high = max(b["high"] for b in seg[:low_idx + 1])
        if after[-1]["close"] > recent_high and after[-1]["close"] > after[-1]["open"]:
            # Check minimal consolidation (at most 2 bars between low and break)
            gap = len(after)
            if gap <= 3:
                return True
    else:
        high_point = max(b["high"] for b in seg)
        high_idx = next(i for i, b in enumerate(seg) if b["high"] == high_point)

        if high_idx < 1 or high_idx >= len(seg) - 1:
            return False

        after = seg[high_idx + 1:]
        if len(after) < 1:
            return False

        recent_low = min(b["low"] for b in seg[:high_idx + 1])
        if after[-1]["close"] < recent_low and after[-1]["close"] < after[-1]["open"]:
            gap = len(after)
            if gap <= 3:
                return True

    return False


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")
    es_m1_bars = get_bars(data_dir, "ES", "M1")

    if not m15_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: Pre-9:30 15M FVG ────────────────────────────────────
    pre_930_fvgs = []
    for f in detect_fvg(m15_bars):
        bar = m15_bars[f["index"]]
        ny = get_ny_time(bar["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            pre_930_fvgs.append(f)

    if not pre_930_fvgs:
        log.event(1, "No Pre-9:30 15M FVG Found", m15_bars[-1]["time"], 0, "M15")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, "Pre-9:30 15M FVGs Identified", m15_bars[-1]["time"], 0, "M15",
              f"Count: {len(pre_930_fvgs)}")

    # ── Step 2-3: Post-9:30 entry ───────────────────────────────────
    m1_start = next(
        (i for i, b in enumerate(m1_bars)
         if get_ny_time(b["time"]).hour >= 9 and get_ny_time(b["time"]).minute >= 30), 0
    )

    trade_taken = False
    has_tapped_fvg = False

    for i in range(m1_start + 5, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])

        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue

        if ny.hour >= 11 and ny.minute > 30:
            break

        if trade_taken:
            break

        # ── Check price taps 15M FVG ────────────────────────────────
        in_fvg = False
        relevant_fvg = None
        for fvg in pre_930_fvgs:
            if fvg["bottom"] <= bar["low"] <= fvg["top"] or fvg["bottom"] <= bar["high"] <= fvg["top"]:
                in_fvg = True
                relevant_fvg = fvg
                break

        if not in_fvg:
            continue

        # Mark first tap
        if not has_tapped_fvg:
            has_tapped_fvg = True
            log.event(2, "Price Tapped 15M FVG Zone", bar["time"],
                      bar["close"], "M1",
                      f"FVG: {relevant_fvg['top']:.2f} - {relevant_fvg['bottom']:.2f}")

        # ── SMT divergence check (NQ vs ES) ─────────────────────────
        smt_dir = None
        if es_m1_bars and len(es_m1_bars) > 10:
            nq_recent = m1_bars[max(0, i - 15):i + 1]
            es_recent = es_m1_bars[-15:] if len(es_m1_bars) >= 15 else es_m1_bars

            nq_low = min(b["low"] for b in nq_recent)
            nq_high = max(b["high"] for b in nq_recent)
            es_low = min(b["low"] for b in es_recent)
            es_high = max(b["high"] for b in es_recent)

            # NQ makes lower low, ES doesn't = bullish div
            if nq_low < bar["low"] and bar["low"] == nq_low and nq_low < es_low:
                smt_dir = "bullish"
            # NQ makes higher high, ES doesn't = bearish div
            if nq_high > bar["high"] and bar["high"] == nq_high and nq_high > es_high:
                smt_dir = "bearish"

        if smt_dir is None:
            continue

        log.event(3, f"SMT Divergence ({smt_dir.upper()})", bar["time"],
                  bar["close"], "M1",
                  "NQ vs ES divergence confirmed")

        # ── 1M FVG detection + W-shape inversion ────────────────────
        seg = m1_bars[max(0, i - 12):i + 1]
        m1_fvgs = detect_fvg(seg)

        if not m1_fvgs:
            continue

        # Check W-shape inversion
        w_shape = detect_w_shape_inversion(seg, len(seg) - 1, smt_dir)

        if not w_shape:
            continue

        # Find an FVG that was inverted by the current close
        inv_fvg = None
        for f in m1_fvgs:
            if smt_dir == "bullish":
                if bar["close"] > f["top"] and bar["close"] > bar["open"]:
                    inv_fvg = f
                    break
            else:
                if bar["close"] < f["bottom"] and bar["close"] < bar["open"]:
                    inv_fvg = f
                    break

        if inv_fvg is None:
            continue

        log.event(4, f"W-Shape iFVG Entry ({smt_dir.upper()})",
                  bar["time"], bar["close"], "M1",
                  f"FVG: {inv_fvg['top']:.2f}-{inv_fvg['bottom']:.2f}")

        if smt_dir == "bullish":
            sl = round(bar["low"] * 0.9998, 5)
            tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
            log.trade("LONG", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"15m_fvg_top": relevant_fvg["top"],
                       "15m_fvg_bottom": relevant_fvg["bottom"],
                       "smt": f"NQ/ES {smt_dir} divergence",
                       "ifvg_top": inv_fvg["top"],
                       "ifvg_bottom": inv_fvg["bottom"],
                       "management": "30% partial at 0.7, BE at first fractal"})
        else:
            sl = round(bar["high"] * 1.0002, 5)
            tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
            log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                      symbol, STRATEGY_NAME,
                      {"15m_fvg_top": relevant_fvg["top"],
                       "15m_fvg_bottom": relevant_fvg["bottom"],
                       "smt": f"NQ/ES {smt_dir} divergence",
                       "ifvg_top": inv_fvg["top"],
                       "ifvg_bottom": inv_fvg["bottom"],
                       "management": "30% partial at 0.7, BE at first fractal"})

        trade_taken = True
        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
