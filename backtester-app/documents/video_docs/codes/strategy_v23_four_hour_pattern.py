"""
Strategy: The 4H Pattern Nobody Talks About
Source: Faiz SMC ("The 4H Pattern Nobody Talks About (step by step)")
Video: https://www.youtube.com/watch?v=a5nZhjyCCJo

Core Concept:
  10AM 4H open = premium/discount divider. 5M/15M PD array + SMT + CISD.
  Short only above open, long only below open. Clean V-shaped reversal.
  TP at -2.0/-2.5 fib expansion. BE after first internal swing.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "FourHourPattern"
SYMBOL = "NQ"
TIMEFRAMES = ["4H", "15M", "M1"]


def find_pd_zone(bars, above=None, below=None):
    fvgs = detect_fvg(bars)
    obs = []
    for i in range(1, len(bars)):
        b, pb = bars[i], bars[i - 1]
        if pb["high"] < b["close"] and pb["low"] > b["open"]:
            obs.append({"type": "OB", "time": b["time"],
                        "top": max(pb["high"], b["open"]),
                        "bottom": min(pb["low"], b["close"])})
    all_zones = fvgs + obs

    if above:
        cands = [z for z in all_zones if z.get("top", 0) > above or z.get("bottom", 0) > above]
        return min(cands, key=lambda z: z.get("top", z.get("bottom", 0))) if cands else None
    if below:
        cands = [z for z in all_zones if z.get("bottom", 0) < below or z.get("top", 0) < below]
        return max(cands, key=lambda z: z.get("bottom", z.get("top", 0))) if cands else None
    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "4H")
    m15_bars = get_bars(data_dir, symbol, "15M")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h4_bars or not m1_bars:
        print("No data found")
        return

    candle_open = 0.0
    candle_time = None
    for b in h4_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == 10 and ny.minute == 0:
            candle_open = b["open"]
            candle_time = b["time"]
            log.event(1, "10AM 4H Open (Premium/Discount)", b["time"],
                      candle_open, "4H", f"Open={candle_open:.2f}")
            break

    if not candle_time:
        log.event(1, "10AM Candle Not Found", h4_bars[-1]["time"], 0, "4H")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── 5M/15M PD Arrays ────────────────────────────────────────────
    m15_left = [b for b in m15_bars if b["time"] < candle_time] if m15_bars else []
    bull_pd = find_pd_zone(m15_left, below=candle_open)
    bear_pd = find_pd_zone(m15_left, above=candle_open)

    log.event(2, "15M PD Arrays", candle_time, candle_open, "15M",
              f"Bull zone (discount): {bull_pd['type']} @ {bull_pd['bottom']:.2f}-{bull_pd['top']:.2f}"
              if bull_pd else "None below"
              f" | Bear zone (premium): {bear_pd['type']} @ {bear_pd['bottom']:.2f}-{bear_pd['top']:.2f}"
              if bear_pd else "None above")

    # ── State Machine ───────────────────────────────────────────────
    state = "WAIT_SWEEP"
    sweep_dir = None
    pd_used = None
    sweep_extreme = 0.0
    trade_taken = False

    m1_start = next(i for i, b in enumerate(m1_bars) if b["time"] >= candle_time)

    for i in range(m1_start + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 10 or ny.hour >= 16:
            continue
        if trade_taken:
            break

        # ── Step 3: Sweep into PD zone ─────────────────────────────
        if state == "WAIT_SWEEP":
            if bear_pd and bar["high"] > bear_pd["top"]:
                sweep_dir = "bearish"
                pd_used = bear_pd
                sweep_extreme = bar["high"]
                state = "WAIT_REVERSAL"
                log.event(3, "Bearish Sweep into Premium PD Zone",
                          bar["time"], bar["high"], "M1",
                          f"Swept {bear_pd['type']} @ {bear_pd['top']:.2f}")

            elif bull_pd and bar["low"] < bull_pd["bottom"]:
                sweep_dir = "bullish"
                pd_used = bull_pd
                sweep_extreme = bar["low"]
                state = "WAIT_REVERSAL"
                log.event(3, "Bullish Sweep into Discount PD Zone",
                          bar["time"], bar["low"], "M1",
                          f"Swept {bull_pd['type']} @ {bull_pd['bottom']:.2f}")

        # ── Step 4-5: CISD entry ──────────────────────────────────
        if state == "WAIT_REVERSAL":
            recent = m1_bars[max(0, i - 8):i + 1]
            cisd = [s for s in detect_cisd(recent) if s["direction"] == sweep_dir]

            if not cisd:
                continue

            log.event(4, f"CISD Entry ({sweep_dir.upper()})", bar["time"],
                      bar["close"], "M1",
                      "Clean V-shape reversal confirmed.")

            if sweep_dir == "bearish":
                sl = round(sweep_extreme * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"fourh_open": candle_open,
                           "pd_type": pd_used["type"], "pd_top": pd_used["top"],
                           "pd_bottom": pd_used["bottom"], "cisd": True})
            else:
                sl = round(sweep_extreme * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"fourh_open": candle_open,
                           "pd_type": pd_used["type"], "pd_top": pd_used["top"],
                           "pd_bottom": pd_used["bottom"], "cisd": True})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
