"""
Strategy: ICT Daily Bias Simplified Strategy
Source: Faiz SMC ("I Simplified ICT Daily Bias.. (Full Trading Strategy)")
Video: https://www.youtube.com/watch?v=YKbkZ4eRd04

Core Concept:
  D1 origin → DOL. H1 order flow confirmation. 15M/5M FVG.
  9:30 AM Judas Swing into FVG → M1 iFVG (check 2M→5M ladder).
  TP 1:2.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "DailyBiasSimplified"
SYMBOL = "NQ"
TIMEFRAMES = ["D1", "H1", "15M", "M5", "M1"]


def determine_dol(d1_bars):
    """Determine DOL from D1 origin."""
    if len(d1_bars) < 3:
        return None, None
    last = d1_bars[-1]
    prev = d1_bars[-2]
    # Check if recent sweep happened
    sw_highs = detect_swing_highs(d1_bars[-10:])
    sw_lows = detect_swing_lows(d1_bars[-10:])

    # If price recently swept a low → target high
    if sw_lows and last["low"] <= sw_lows[-1]["price"]:
        return "bullish", sw_highs[-1]["price"] if sw_highs else last["high"] * 1.01
    # If price recently swept a high → target low
    if sw_highs and last["high"] >= sw_highs[-1]["price"]:
        return "bearish", sw_lows[-1]["price"] if sw_lows else last["low"] * 0.99
    return None, None


def aggregate(m1_bars, m):
    result = []
    for j in range(0, len(m1_bars), m):
        chunk = m1_bars[j:j + m]
        if not chunk:
            continue
        result.append({
            "time": chunk[0]["time"],
            "open": chunk[0]["open"],
            "high": max(b["high"] for b in chunk),
            "low": min(b["low"] for b in chunk),
            "close": chunk[-1]["close"],
        })
    return result


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    d1_bars = get_bars(data_dir, symbol, "D1")
    h1_bars = get_bars(data_dir, symbol, "H1")
    m15_bars = get_bars(data_dir, symbol, "15M")
    m5_bars = get_bars(data_dir, symbol, "5M")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not d1_bars or not h1_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: D1 origin → DOL ─────────────────────────────────────
    bias, dol = determine_dol(d1_bars)
    if not bias:
        log.event(1, "No Clear DOL from D1", d1_bars[-1]["time"],
                  d1_bars[-1]["close"], "D1", "Skip.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"D1 Bias: {bias.upper()}, DOL={dol:.2f}",
              d1_bars[-1]["time"], d1_bars[-1]["close"], "D1",
              "Origin identified from daily sweep/FVG.")

    # ── Step 2: H1 order flow confirmation ──────────────────────────
    h1_fvgs = detect_fvg(h1_bars[-24:])
    bias_fvgs = [f for f in h1_fvgs if f["direction"] == bias]
    if not bias_fvgs:
        log.event(2, "H1 No Confirmation", h1_bars[-1]["time"],
                  h1_bars[-1]["close"], "H1",
                  f"No {bias} FVGs respected. Skip.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(2, f"H1 Order Flow Confirmed ({bias.upper()})",
              h1_bars[-1]["time"], h1_bars[-1]["close"], "H1",
              f"{len(bias_fvgs)} {bias} FVGs respected.")

    # ── Step 3: 15M/5M FVG in bias direction ───────────────────────
    m15_fvgs = detect_fvg(m15_bars[-20:]) if m15_bars else []
    m5_fvgs = detect_fvg(m5_bars[-20:]) if m5_bars else []

    target_fvg = None
    for f in m15_fvgs:
        if f["direction"] == bias:
            target_fvg = f
            break
    if not target_fvg:
        for f in m5_fvgs:
            if f["direction"] == bias:
                target_fvg = f
                break

    if not target_fvg:
        log.event(3, "No 15M/5M FVG Found", m1_bars[-1]["time"], 0, "15M/5M")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(3, "Target HTF FVG (15M/5M)", target_fvg["time"],
              target_fvg.get("avg", 0), "M15" if target_fvg in m15_fvgs else "M5",
              f"Top={target_fvg['top']:.2f}, Bottom={target_fvg['bottom']:.2f}")

    # ── Step 4-6: 9:30 AM → Judas Swing → iFVG ────────────────────
    m1_start = next(
        (i for i, b in enumerate(m1_bars)
         if get_ny_time(b["time"]).hour >= 9 and get_ny_time(b["time"]).minute >= 30), 0
    )

    state = "WAIT_FVG_TAP"
    trade_taken = False

    for i in range(m1_start + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11:
            break
        if trade_taken:
            break

        if state == "WAIT_FVG_TAP":
            in_fvg = target_fvg["bottom"] <= bar["close"] <= target_fvg["top"]
            if not in_fvg:
                continue
            state = "WAIT_IFVG"
            log.event(4, "Price Entered HTF FVG (Judas Swing)", bar["time"],
                      bar["close"], "M1")

        if state == "WAIT_IFVG":
            # Check iFVG on multi-TF ladder (1M → 5M)
            seg = m1_bars[max(0, i - 10):i + 1]
            best_ifvg = None
            best_tf = 0
            for m in [1, 2, 3, 4, 5]:
                candles = seg if m == 1 else aggregate(seg, m)
                ifvgs = [f for f in detect_ifvg(candles) if f["direction"] == bias]
                for iv in ifvgs:
                    if m > best_tf:
                        best_ifvg = iv
                        best_tf = m

            if not best_ifvg:
                continue

            # Check displacement volume (large candle)
            body = abs(bar["close"] - bar["open"])
            recent = m1_bars[max(0, i - 10):i]
            avg_body = sum(abs(b["close"] - b["open"]) for b in recent) / max(len(recent), 1)
            if body < avg_body * 1.3:
                continue

            log.event(5, f"iFVG Entry (M{best_tf})", bar["time"],
                      bar["close"], f"M{best_tf}",
                      f"High-volume inversion confirmed.")

            if bias == "bullish":
                sl = round(min(b["low"] for b in m1_bars[max(0, i - 3):i + 1]) * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"d1_bias": bias, "dol": dol,
                           "htf_fvg_top": target_fvg["top"],
                           "htf_fvg_bottom": target_fvg["bottom"],
                           "ifvg_tf": f"M{best_tf}"})
            else:
                sl = round(max(b["high"] for b in m1_bars[max(0, i - 3):i + 1]) * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"d1_bias": bias, "dol": dol,
                           "htf_fvg_top": target_fvg["top"],
                           "htf_fvg_bottom": target_fvg["bottom"],
                           "ifvg_tf": f"M{best_tf}"})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
