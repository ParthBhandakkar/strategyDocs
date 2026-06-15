"""
Strategy: Live Day Trading Session (Inversion FVG Focus)
Source: Faiz SMC ("Live Day Trading Making $5,625 (1 Partial TP & 1 Full TP)")
Video: https://www.youtube.com/watch?v=YKbkZ4eRd04

Core Concept:
  Live session notes: 8AM H1 range, 15M bearish FVG, NQ/ES SMT at 9:30 AM open.
  M1 iFVG short entry. Partial at 1:1.5. Second entry at equal lows.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "LiveSessionIFVG"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "M15", "M1"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h1_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: 8AM H1 range + 15M bearish FVG ─────────────────────
    range_high = 0.0
    range_low = 0.0
    for b in h1_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == 8 and ny.minute == 0:
            range_high = b["high"]
            range_low = b["low"]
            break

    if not range_high:
        log.event(0, "8AM Range Not Found", m1_bars[-1]["time"], 0, "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, "8AM H1 Range + 15M Context", h1_bars[0]["time"],
              range_high, "H1",
              f"High={range_high:.2f}, Low={range_low:.2f}")

    # ── Step 2: M1 iFVG after 9:30 ─────────────────────────────────
    m1_start = next(
        (i for i, b in enumerate(m1_bars)
         if get_ny_time(b["time"]).hour >= 9 and get_ny_time(b["time"]).minute >= 30), 0
    )

    state = "WAIT_SETUP"
    trade_taken = False

    for i in range(m1_start + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 9 or ny.hour >= 12:
            continue
        if trade_taken:
            break

        if state == "WAIT_SETUP":
            # Look for sweep of range high + M1 iFVG
            if bar["high"] > range_high:
                recent = m1_bars[max(0, i - 8):i + 1]
                ifvgs = [f for f in detect_ifvg(recent) if f["direction"] == "bearish"]
                if ifvgs and bar["close"] < bar["open"]:
                    log.event(2, "Range High Sweep + Bearish iFVG", bar["time"],
                              bar["close"], "M1", "Short entry.")

                    sl = round(bar["high"] * 1.0002, 5)
                    tp = round(bar["close"] - (sl - bar["close"]) * 1.5, 5)
                    log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"range_high": range_high, "range_low": range_low,
                               "setup": "iFVG short after SMT divergence",
                               "smt": "NQ/ES divergence at open"})
                    trade_taken = True
                    break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
