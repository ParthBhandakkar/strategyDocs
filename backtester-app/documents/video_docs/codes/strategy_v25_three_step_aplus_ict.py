"""
Strategy: The 3-Step A+ ICT Strategy That Works Everyday!
Source: Faiz SMC ("The 3-Step A+ ICT Strategy That Works Everyday! (Stupid Simple)")
Video: https://www.youtube.com/watch?v=7rpncfx75HY

Core Concept:
  1) H1 trend bias (which PD Arrays are respected/broken).
  2) Post-9:30 AM: 5M/15M FVG toward DOL.
  3) Price taps FVG → multi-TF inversion ladder (1M up to 5M).
  Trade the highest TF inversion gap found. V-shape required.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "ThreeStepAPlusICT"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "15M", "5M", "M5", "M2", "M1"]


def determine_h1_bias(h1_bars):
    """Determine H1 trend by checking which PD Arrays are respected/broken."""
    if len(h1_bars) < 12:
        return None

    recent = h1_bars[-12:]
    fvgs = detect_fvg(recent)
    bull_fvgs = [f for f in fvgs if f["direction"] == "bullish"]
    bear_fvgs = [f for f in fvgs if f["direction"] == "bearish"]

    # Check if price broke recent swing levels
    sw_highs = detect_swing_highs(recent)
    sw_lows = detect_swing_lows(recent)

    last = recent[-1]["close"]
    if sw_highs and last > max(s["price"] for s in sw_highs[-3:]):
        return "bullish"
    if sw_lows and last < min(s["price"] for s in sw_lows[-3:]):
        return "bearish"

    # Fallback: more bull FVGs than bear
    if len(bull_fvgs) > len(bear_fvgs):
        return "bullish"
    if len(bear_fvgs) > len(bull_fvgs):
        return "bearish"
    return None


def find_highest_tf_inversion(m1_bars, segment, up_to_minutes=5):
    """Multi-TF ladder: scan 1M to 5M for highest TF inverted FVG."""
    tfs = []
    for m in [1, 2, 3, 4, 5]:
        name = f"M{m}"
        if name == "M1":
            tfs.append((m, segment))
        else:
            # Aggregate candles from M1 to approximate higher TF
            aggregated = []
            chunk_size = m
            for j in range(0, len(segment), chunk_size):
                chunk = segment[j:j + chunk_size]
                if not chunk:
                    continue
                agg = {
                    "time": chunk[0]["time"],
                    "open": chunk[0]["open"],
                    "high": max(b["high"] for b in chunk),
                    "low": min(b["low"] for b in chunk),
                    "close": chunk[-1]["close"],
                }
                aggregated.append(agg)
            tfs.append((m, aggregated))

    best = None
    best_tf = 0

    for tf_m, bars in tfs:
        fvgs = detect_fvg(bars)
        ifvgs = detect_ifvg(bars)
        for iv in ifvgs:
            if iv["direction"] in ("bullish", "bearish") and tf_m > best_tf:
                # Check clean V-shape (gap not too old)
                best = iv
                best_tf = tf_m

    return best, best_tf


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m5_bars = get_bars(data_dir, symbol, "M5")
    m15_bars = get_bars(data_dir, symbol, "15M")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h1_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: H1 Trend Bias ───────────────────────────────────────
    bias = determine_h1_bias(h1_bars)
    if not bias:
        log.event(1, "No Clear H1 Trend Bias", h1_bars[-1]["time"],
                  h1_bars[-1]["close"], "H1",
                  "PD Arrays not clearly respected/broken. Skip.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"H1 Trend Bias: {bias.upper()}", h1_bars[-1]["time"],
              h1_bars[-1]["close"], "H1",
              "Direction established from HTF PD Array structure.")

    # ── Step 2: Post-9:30 AM FVG toward bias direction ─────────────
    trade_start_idx = next(
        (i for i, b in enumerate(m1_bars)
         if get_ny_time(b["time"]).hour >= 9 and get_ny_time(b["time"]).minute >= 30),
        0
    )

    # ── State Machine ───────────────────────────────────────────────
    state = "WAIT_HTF_FVG"
    htf_fvg = None
    trade_taken = False
    sweep_dir = None
    sweep_extreme = 0.0

    for i in range(trade_start_idx + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])

        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 12:
            break
        if trade_taken:
            break

        # ── Step 2: Find 5M/15M FVG in bias direction ───────────
        if state == "WAIT_HTF_FVG" and m5_bars:
            # Check recent M5 bars for FVGs
            m5_idx = next(
                (j for j, b in enumerate(m5_bars) if b["time"] >= bar["time"]),
                None
            )
            if m5_idx and m5_idx > 2:
                m5_recent = m5_bars[max(0, m5_idx - 5):m5_idx + 1]
                m5_fvgs = detect_fvg(m5_recent)
                for f in m5_fvgs:
                    if f["direction"] == bias:
                        htf_fvg = f
                        state = "WAIT_FVG_TAP"
                        log.event(2, f"M5 FVG in {bias.upper()} Direction",
                                  f["time"], f.get("avg", 0), "M5",
                                  f"Top={f['top']:.2f}, Bottom={f['bottom']:.2f}")
                        break

        # ── Step 3: Price taps into HTF FVG ─────────────────────
        if state == "WAIT_FVG_TAP" and htf_fvg:
            in_fvg = htf_fvg["bottom"] <= bar["close"] <= htf_fvg["top"]
            if not in_fvg:
                continue

            state = "WAIT_M1_SWEEP"
            log.event(3, "Price Entered HTF FVG", bar["time"],
                      bar["close"], "M1")

        # ── M1 sweep inside FVG ─────────────────────────────────
        if state == "WAIT_M1_SWEEP":
            recent_m1 = m1_bars[max(0, i - 8):i + 1]
            sw_h = detect_swing_highs(recent_m1)
            sw_l = detect_swing_lows(recent_m1)

            if bias == "bearish" and sw_h and sw_h[-1]["price"] > htf_fvg["bottom"]:
                sweep_dir = "bearish"
                sweep_extreme = sw_h[-1]["price"]
                state = "WAIT_INVERSION_LADDER"
                log.event(3, "M1 Sweep (Bearish)", bar["time"],
                          bar["close"], "M1")
            elif bias == "bullish" and sw_l and sw_l[-1]["price"] < htf_fvg["top"]:
                sweep_dir = "bullish"
                sweep_extreme = sw_l[-1]["price"]
                state = "WAIT_INVERSION_LADDER"
                log.event(3, "M1 Sweep (Bullish)", bar["time"],
                          bar["close"], "M1")

        # ── Multi-TF Inversion Ladder ───────────────────────────
        if state == "WAIT_INVERSION_LADDER":
            seg = m1_bars[max(0, i - 12):i + 1]
            best_ifvg, best_tf = find_highest_tf_inversion(None, seg, 5)

            if not best_ifvg or best_ifvg["direction"] != sweep_dir:
                continue

            log.event(4, f"Multi-TF Inversion (M{best_tf})", bar["time"],
                      bar["close"], f"M{best_tf}",
                      f"Highest TF inversion gap found. Entry triggered.")

            if sweep_dir == "bearish":
                sl = round(sweep_extreme * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"h1_bias": bias,
                           "htf_fvg_top": htf_fvg["top"],
                           "htf_fvg_bottom": htf_fvg["bottom"],
                           "inversion_tf": f"M{best_tf}",
                           "sweep_extreme": sweep_extreme})
            else:
                sl = round(sweep_extreme * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"h1_bias": bias,
                           "htf_fvg_top": htf_fvg["top"],
                           "htf_fvg_bottom": htf_fvg["bottom"],
                           "inversion_tf": f"M{best_tf}",
                           "sweep_extreme": sweep_extreme})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
