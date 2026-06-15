"""
Strategy: Dumbest ICT Gold Trading Strategy Makes $10,000/Month
Source: Faiz SMC
Video: https://www.youtube.com/watch?v=7_9bekMCNZA

Core Concept:
  Trade only during Asia session (20:00 – 00:00 NY). Use 1-hour order flow
  for bias. Wait for price to tap into a 1-hour PDA (FVG/OB). Drop to 5M
  and wait for a liquidity sweep. Identify 5M FVGs within the dealing range.
  Enter on inversion of all FVGs. 30% partial at 1:1, full TP at 1:2.
  Move to break-even at the nearest liquidity pool.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "DumbestGold10000"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["H1", "M5"]


def find_sweep_segment(bars: list, start_idx: int, lookback: int = 8):
    """Return (sweep_idx, sweep_high, sweep_low) if a sweep is found."""
    seg = bars[max(0, start_idx - lookback):start_idx + 1]
    seg_high = max(b["high"] for b in seg)
    seg_low = min(b["low"] for b in seg)

    for k in range(1, len(seg)):
        if seg[k]["high"] > max(b["high"] for b in seg[:k]):
            return k, seg_high, seg_low
        if seg[k]["low"] < min(b["low"] for b in seg[:k]):
            return k, seg_high, seg_low
    return None, seg_high, seg_low


def all_fvgs_inverted(bars: list, fvg_list: list, direction: str) -> bool:
    """Check if the last bar closes past all FVGs in the given direction."""
    last = bars[-1]
    for f in fvg_list:
        if direction == "bullish":
            if not (last["close"] > f["top"] and last["close"] > last["open"]):
                return False
        else:
            if not (last["close"] < f["bottom"] and last["close"] < last["open"]):
                return False
    return True


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m5_bars = get_bars(data_dir, symbol, "M5")

    if not h1_bars or not m5_bars:
        print("No data found")
        return

    # ── Step 1: H1 order flow bias ──────────────────────────────────
    h1_bias = "bullish" if h1_bars[-1]["close"] > h1_bars[-1]["open"] else "bearish"
    h1_fvgs = detect_fvg(h1_bars)

    if not h1_fvgs:
        log.event(1, "H1 Bias (No FVG found)", h1_bars[-1]["time"],
                  h1_bars[-1]["close"], "H1",
                  f"Bias={h1_bias}, no PD arrays available")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, "H1 Order Flow + PD Arrays", h1_bars[-1]["time"],
              h1_bars[-1]["close"], "H1",
              f"Bias={h1_bias}, FVGs={len(h1_fvgs)}")

    # ── Step 2-3: Asia session (20:00-00:00 NY) ─────────────────────
    trade_taken = False
    state = "WAIT_HTF_TAP"

    for i in range(10, len(m5_bars)):
        bar = m5_bars[i]
        ny = get_ny_time(bar["time"])

        # Only Asia session: 20:00 – 00:00 NY
        if not (ny.hour >= 20 or ny.hour < 0):
            continue

        if trade_taken:
            break

        # ── Step 2: Wait for price to tap H1 PDA ────────────────────
        if state == "WAIT_HTF_TAP":
            in_fvg = False
            tapped_fvg = None
            for fvg in h1_fvgs:
                if fvg["direction"] != h1_bias:
                    continue
                if fvg["bottom"] <= bar["low"] <= fvg["top"] or fvg["bottom"] <= bar["high"] <= fvg["top"]:
                    in_fvg = True
                    tapped_fvg = fvg
                    break

            if not in_fvg:
                continue

            state = "WAIT_SWEEP"
            log.event(2, "Price Tapped H1 PDA", bar["time"],
                      bar["close"], "M5",
                      f"H1 FVG: {tapped_fvg['top']:.2f} - {tapped_fvg['bottom']:.2f}")

        # ── Step 3: Wait for liquidity sweep on 5M ──────────────────
        if state == "WAIT_SWEEP":
            sweep_info = find_sweep_segment(m5_bars, i, lookback=6)
            sweep_idx = sweep_info[0]
            seg_high = sweep_info[1]
            seg_low = sweep_info[2]

            if sweep_idx is None:
                continue

            # Check sweep was in the correct direction
            if h1_bias == "bullish":
                # Expect sell-side sweep (low swept)
                if m5_bars[i]["low"] > seg_low and m5_bars[i]["high"] < seg_high:
                    continue
                log.event(3, "5M Liquidity Sweep (Sell-side)", bar["time"],
                          bar["close"], "M5",
                          f"Range: {seg_high:.2f} - {seg_low:.2f}")
            else:
                if m5_bars[i]["high"] < seg_high and m5_bars[i]["low"] > seg_low:
                    continue
                log.event(3, "5M Liquidity Sweep (Buy-side)", bar["time"],
                          bar["close"], "M5",
                          f"Range: {seg_high:.2f} - {seg_low:.2f}")

            state = "WAIT_FVG_INVERSION"

        # ── Step 3 cont: Identify 5M FVGs + inversion ──────────────
        if state == "WAIT_FVG_INVERSION":
            seg = m5_bars[max(0, i - 12):i + 1]
            fvgs_in_range = detect_fvg(seg)

            if not fvgs_in_range:
                if i > 15 and bar["low"] < seg_low or bar["high"] > seg_high:
                    state = "WAIT_SWEEP"
                continue

            # Filter FVGs matching bias direction
            fvgs_aligned = [f for f in fvgs_in_range if f["direction"] == h1_bias]
            if not fvgs_aligned:
                if i > 15 and bar["low"] < seg_low or bar["high"] > seg_high:
                    state = "WAIT_SWEEP"
                continue

            # Check inversion: price must close past all FVGs
            if not all_fvgs_inverted(seg, fvgs_aligned, h1_bias):
                if i > 15 and bar["low"] < seg_low or bar["high"] > seg_high:
                    state = "WAIT_SWEEP"
                continue

            inverting_bar = seg[-1]
            log.event(4, f"5M FVG Inversion ({h1_bias.upper()})",
                      inverting_bar["time"], inverting_bar["close"], "M5",
                      f"FVGs inversed: {len(fvgs_aligned)}")

            if h1_bias == "bullish":
                entry = inverting_bar["close"]
                sl = round(inverting_bar["low"] * 0.9998, 5)
                tp1 = round(entry + (entry - sl), 5)
                tp2 = round(entry + (entry - sl) * 2, 5)
                log.trade("LONG", entry, sl, tp2, inverting_bar["time"],
                          symbol, STRATEGY_NAME,
                          {"strategy": "30% partial at 1:1, BE at nearest liquidity",
                           "tp_partial": tp1, "tp_final": tp2,
                           "h1_bias": h1_bias, "session": "Asia",
                           "h1_fvg_top": tapped_fvg["top"] if tapped_fvg else None,
                           "h1_fvg_bottom": tapped_fvg["bottom"] if tapped_fvg else None})
            else:
                entry = inverting_bar["close"]
                sl = round(inverting_bar["high"] * 1.0002, 5)
                tp1 = round(entry - (sl - entry), 5)
                tp2 = round(entry - (sl - entry) * 2, 5)
                log.trade("SHORT", entry, sl, tp2, inverting_bar["time"],
                          symbol, STRATEGY_NAME,
                          {"strategy": "30% partial at 1:1, BE at nearest liquidity",
                           "tp_partial": tp1, "tp_final": tp2,
                           "h1_bias": h1_bias, "session": "Asia",
                           "h1_fvg_top": tapped_fvg["top"] if tapped_fvg else None,
                           "h1_fvg_bottom": tapped_fvg["bottom"] if tapped_fvg else None})

            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
