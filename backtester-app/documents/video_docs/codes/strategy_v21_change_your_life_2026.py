"""
Strategy: This Trading Strategy Will Change Your Life In 2026
Source: Faiz SMC ("This Trading Strategy Will Change Your Life In 2026")
Video: https://www.youtube.com/watch?v=lN7oMZ_S8xI

Core Concept:
  10AM 4H candle open. A+ Setup: tap 5M/15M PD Array (FVG/OB) below (long) or
  above (short) open. A Setup: immediate SMT divergence at open.
  M1 CISD entry. Fib expansion targets (-2.0, -2.5, -4.0).
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "ChangeYourLife2026"
SYMBOL = "NQ"
TIMEFRAMES = ["4H", "15M", "M1"]


def find_pd_array_zone(bars, above_price=None, below_price=None, lookback=40):
    """Find nearest FVG or order block above or below a price on given bars."""
    fvgs = detect_fvg(bars)
    obs = []
    for i in range(1, len(bars)):
        b = bars[i]
        pb = bars[i - 1]
        if pb["high"] < b["close"] and pb["low"] > b["open"]:
            obs.append({"type": "OB", "time": b["time"],
                        "top": max(pb["high"], b["open"]),
                        "bottom": min(pb["low"], b["close"])})

    candidates = fvgs + obs

    if above_price:
        above = [c for c in candidates
                 if c.get("top", 0) > above_price or c.get("bottom", 0) > above_price]
        return min(above, key=lambda x: x.get("top", x.get("bottom", 0))) if above else None

    if below_price:
        below = [c for c in candidates
                 if c.get("bottom", 0) < below_price or c.get("top", 0) < below_price]
        return max(below, key=lambda x: x.get("bottom", x.get("top", 0))) if below else None

    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "4H")
    m15_bars = get_bars(data_dir, symbol, "15M")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h4_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: 10AM 4H candle open ─────────────────────────────────
    candle_open = 0.0
    candle_time = None
    for b in h4_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == 10 and ny.minute == 0:
            candle_open = b["open"]
            candle_time = b["time"]
            log.event(1, "10AM 4H Candle Open", b["time"], candle_open, "4H",
                      f"Open={candle_open:.2f}")
            break

    if not candle_time:
        log.event(1, "10AM 4H Candle Not Found", h4_bars[-1]["time"], 0, "4H")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── Step 2: Identify PD Arrays (A+ Setup) ───────────────────────
    m15_left = [b for b in m15_bars if b["time"] < candle_time]
    bull_pd = find_pd_array_zone(m15_left, below_price=candle_open) if m15_left else None
    bear_pd = find_pd_array_zone(m15_left, above_price=candle_open) if m15_left else None

    log.event(2, "15M PD Arrays Relative to Open", candle_time, candle_open, "15M",
              f"Bull (below): {bull_pd['type']} @ {bull_pd['bottom']:.2f}-{bull_pd['top']:.2f}"
              if bull_pd else "None"
              | f" | Bear (above): {bear_pd['type']} @ {bear_pd['bottom']:.2f}-{bear_pd['top']:.2f}"
              if bear_pd else "None")

    # ── State Machine on M1 ─────────────────────────────────────────
    state = "WAIT_SWEEP"
    setup_type = None
    sweep_direction = None
    fib_high = 0.0
    fib_low = 0.0
    sweep_extreme = 0.0
    trade_taken = False

    m1_start = next(
        i for i, b in enumerate(m1_bars) if b["time"] >= candle_time
    )

    for i in range(m1_start + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 10 or ny.hour >= 16:
            continue
        if trade_taken:
            break

        # ── Step 3: Monitor sweeps ────────────────────────────────
        if state == "WAIT_SWEEP":
            if bear_pd and bar["high"] > bear_pd["top"]:
                # A+ short: price swept above bearish PD array
                sweep_direction = "bearish"
                setup_type = "A+ (PD Array Tap)"
                sweep_extreme = bar["high"]
                state = "WAIT_SMT"
                log.event(3, "Bearish Sweep (A+ Short)", bar["time"],
                          bar["high"], "M1",
                          f"Swept 15M PD above open. "
                          f"Looking for SMT divergence.")

            elif bull_pd and bar["low"] < bull_pd["bottom"]:
                sweep_direction = "bullish"
                setup_type = "A+ (PD Array Tap)"
                sweep_extreme = bar["low"]
                state = "WAIT_SMT"
                log.event(3, "Bullish Sweep (A+ Long)", bar["time"],
                          bar["low"], "M1",
                          f"Swept 15M PD below open. "
                          f"Looking for SMT divergence.")

        # ── Step 3 cont: SMT + CISD entry ───────────────────────────
        if state == "WAIT_SMT":
            recent = m1_bars[max(0, i - 8):i + 1]
            cisd = [s for s in detect_cisd(recent)
                    if s["direction"] == sweep_direction]

            if not cisd:
                continue

            # A+ setup complete: PD tap + CISD
            trigger = "CISD"
            log.event(4, f"{setup_type} + {trigger}", bar["time"],
                      bar["close"], "M1",
                      f"Entry triggered.")

            # Fib expansion targets
            pre_bars = m1_bars[max(0, i - 20):i + 1]
            lows = [b["low"] for b in pre_bars]
            highs = [b["high"] for b in pre_bars]
            fib_low = min(lows)
            fib_high = max(highs)

            if sweep_direction == "bearish":
                sl = round(sweep_extreme * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                fib_target = fib_expansion(fib_low, fib_high, 2.0)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"fourh_open": candle_open, "setup": setup_type,
                           "pd_array": bear_pd["type"] if bear_pd else None,
                           "pd_price": bear_pd["top"] if bear_pd else None,
                           "fib_target_2_0": fib_target,
                           "trigger": trigger, "smt": True})
            else:
                sl = round(sweep_extreme * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                fib_target = fib_expansion(fib_low, fib_high, 2.0)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"fourh_open": candle_open, "setup": setup_type,
                           "pd_array": bull_pd["type"] if bull_pd else None,
                           "pd_price": bull_pd["bottom"] if bull_pd else None,
                           "fib_target_2_0": fib_target,
                           "trigger": trigger, "smt": True})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
