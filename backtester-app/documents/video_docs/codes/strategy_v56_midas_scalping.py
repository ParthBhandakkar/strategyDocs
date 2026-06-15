"""
Strategy: Midas Model Scalping Strategy (Gold Asian Session)
Source: Faiz SMC ("This Gold Scalping Strategy Works Everyday! (Easy & Profitable)")
Video: https://www.youtube.com/watch?v=Ei0MtKztZtA

Core Concept:
  Gold only. 15M unswept high/low before 8PM NY (Asian session open).
  After 8PM open, wait for sweep of either level.
  Drop to 1M: look for MSS with displacement (sharp move + FVG).
  Enter at FVG/breaker retest, or directly at MSS shift.
  9PM session same logic. Max 1 trade per session.
  1:2 target, move SL to BE at 1:1.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "MidasScalping"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M15", "M1"]


def find_unswept_levels(m15_bars, before_hour, lookback=10):
    """Find the most recent unswept high and low before before_hour."""
    pre = [b for b in m15_bars if get_ny_time(b["time"]).hour < before_hour]
    if len(pre) < 3:
        return None, None, None, None

    recent = pre[-lookback:]
    high = max(b["high"] for b in recent)
    low = min(b["low"] for b in recent)

    # Ensure these levels haven't been swept in the lookback
    for b in recent:
        if b["high"] > high and b["time"] != high:
            pass  # There's a higher point — find it
        if b["low"] < low and b["time"] != low:
            pass

    # Actually find the LAST unswept level before the session
    highest_bar = max(recent, key=lambda b: b["high"])
    lowest_bar = min(recent, key=lambda b: b["low"])

    return highest_bar["high"], lowest_bar["low"], highest_bar["time"], lowest_bar["time"]


def detect_displacement_mss(bars: list, idx: int):
    """
    Check for MSS with displacement at bar idx.
    Returns (direction, fvg_found) or (None, False).
    """
    seg = bars[max(0, idx - 6):idx + 1]
    if len(seg) < 3:
        return None, False

    bar = bars[idx]

    # Bullish displacement: breaks above recent high with strong close
    recent_high = max(b["high"] for b in seg[:-1])
    if bar["high"] > recent_high and bar["close"] > bar["open"]:
        # Check for FVG in the displacement
        for k in range(1, len(seg) - 1):
            if seg[k]["low"] > seg[k - 1]["high"]:
                return "bullish", True
        return "bullish", False

    # Bearish displacement
    recent_low = min(b["low"] for b in seg[:-1])
    if bar["low"] < recent_low and bar["close"] < bar["open"]:
        for k in range(1, len(seg) - 1):
            if seg[k]["high"] < seg[k - 1]["low"]:
                return "bearish", True
        return "bearish", False

    return None, False


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m15_bars or not m1_bars:
        print("No data found")
        return

    # ── Process 8PM and 9PM sessions ────────────────────────────────
    for session_hour in [20, 21]:
        session_label = f"{session_hour - 8}PM" if session_hour <= 21 else "9PM"

        # Find unswept levels before session
        pre_high, pre_low, pre_high_time, pre_low_time = find_unswept_levels(
            m15_bars, session_hour
        )

        if pre_high is None:
            continue

        log.event(1, f"{session_label} Session: Pre-Levels",
                  pre_high_time, pre_high, "M15",
                  f"Unswept H={pre_high:.2f}, L={pre_low:.2f}")

        # Find M1 bars in session window (up to midnight)
        session_m1 = [
            (j, b) for j, b in enumerate(m1_bars)
            if get_ny_time(b["time"]).hour >= session_hour
            and get_ny_time(b["time"]).hour < 24
        ]

        if not session_m1:
            continue

        trade_taken = False
        state = "WAIT_SWEEP"

        for j, bar in session_m1:
            if trade_taken:
                break

            # ── Wait for sweep ──────────────────────────────────────
            if state == "WAIT_SWEEP":
                if bar["low"] < pre_low:
                    log.event(2, f"{session_label}: Low Swept", bar["time"],
                              bar["low"], "M1")
                    state = "WAIT_MSS"
                elif bar["high"] > pre_high:
                    log.event(2, f"{session_label}: High Swept", bar["time"],
                              bar["high"], "M1")
                    state = "WAIT_MSS"

            # ── Wait for MSS with displacement ──────────────────────
            elif state == "WAIT_MSS":
                direction, has_fvg = detect_displacement_mss(m1_bars, j)

                if direction is None:
                    continue

                log.event(3, f"{session_label}: MSS + "
                          f"{'Displacement with FVG' if has_fvg else 'Displacement'} "
                          f"({direction.upper()})",
                          bar["time"], bar["close"], "M1")

                if direction == "bullish":
                    sl = round(bar["low"] * 0.9998, 5)
                    tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                    log.trade("LONG", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"session": session_label,
                               "pre_high": pre_high, "pre_low": pre_low,
                               "has_fvg": has_fvg,
                               "management": "BE at 1:1, TP at 1:2"})
                else:
                    sl = round(bar["high"] * 1.0002, 5)
                    tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                    log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"session": session_label,
                               "pre_high": pre_high, "pre_low": pre_low,
                               "has_fvg": has_fvg,
                               "management": "BE at 1:1, TP at 1:2"})

                trade_taken = True
                break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
