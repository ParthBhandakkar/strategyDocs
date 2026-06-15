"""
Strategy: Easy 9AM Candle PO3 Strategy
Source: Faiz SMC ("Easy 9AM Candle PO3 Strategy That Actually Works!")
Video: https://www.youtube.com/watch?v=dyGl-XkMUwQ

Core Concept:
  8AM H1 candle high/low. Sweep at 9AM → M1 MSS + close back inside.
  Entry at M1 breaker block retest. TP = opposite end of 8AM range.
  One trade/day, NQ only.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "Easy9AMPO3"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "M1"]


def find_breaker_block(bars, direction):
    """Find a 1M breaker block in the given direction."""
    for i in range(2, len(bars)):
        b = bars[i]
        pb = bars[i - 1]
        ppb = bars[i - 2]
        if direction == "bullish":
            if b["low"] < pb["low"] and b["close"] > pb["high"]:
                return {"type": "breaker", "top": max(pb["high"], b["open"]),
                        "bottom": min(pb["low"], b["close"]),
                        "time": b["time"]}
        else:
            if b["high"] > pb["high"] and b["close"] < pb["low"]:
                return {"type": "breaker", "top": max(pb["high"], b["open"]),
                        "bottom": min(pb["low"], b["close"]),
                        "time": b["time"]}
    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h1_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: 8AM candle range ────────────────────────────────────
    eight_high = 0.0
    eight_low = 0.0
    found = False

    for b in h1_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == 8 and ny.minute == 0:
            eight_high = b["high"]
            eight_low = b["low"]
            log.event(1, "8AM H1 Candle Range", b["time"], eight_high, "H1",
                      f"High={eight_high:.2f}, Low={eight_low:.2f}")
            found = True
            break

    if not found:
        log.event(1, "8AM Candle Not Found", h1_bars[-1]["time"], 0, "H1")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── State Machine on M1 ─────────────────────────────────────────
    state = "WAIT_SWEEP"
    sweep_dir = None
    sweep_extreme = 0.0
    trade_taken = False

    # Start after 9AM
    m1_start = next(
        (i for i, b in enumerate(m1_bars)
         if get_ny_time(b["time"]).hour >= 9), 0
    )

    for i in range(m1_start + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 9 or ny.hour >= 11:
            continue
        if trade_taken:
            break

        # ── Step 2: Sweep 8AM boundary ───────────────────────────
        if state == "WAIT_SWEEP":
            if bar["high"] > eight_high:
                sweep_dir = "bearish"
                sweep_extreme = bar["high"]
                state = "WAIT_MSS"
                log.event(2, "8AM High Swept (Short Setup)", bar["time"],
                          bar["high"], "M1")
            elif bar["low"] < eight_low:
                sweep_dir = "bullish"
                sweep_extreme = bar["low"]
                state = "WAIT_MSS"
                log.event(2, "8AM Low Swept (Long Setup)", bar["time"],
                          bar["low"], "M1")

        # ── Step 3: MSS + close inside ───────────────────────────
        if state == "WAIT_MSS":
            recent = m1_bars[max(0, i - 8):i + 1]
            mss_list = detect_mss(recent)
            valid_mss = [s for s in mss_list if s["direction"] == sweep_dir]

            if not valid_mss:
                continue

            # Check close inside 8AM range
            inside = False
            if sweep_dir == "bearish":
                inside = bar["close"] < eight_high
            else:
                inside = bar["close"] > eight_low

            if not inside:
                continue

            log.event(3, f"MSS + Close Inside 8AM Range ({sweep_dir.upper()})",
                      bar["time"], bar["close"], "M1")

            state = "WAIT_BREAKER"

        # ── Step 4: Breaker block entry ──────────────────────────
        if state == "WAIT_BREAKER":
            seg = m1_bars[max(0, i - 10):i + 2]
            breaker = find_breaker_block(seg, sweep_dir)

            if not breaker:
                # Enter directly if no breaker found
                entry = bar["close"]
                entry_type = "market (no breaker)"
            else:
                entry = (breaker["top"] + breaker["bottom"]) / 2
                entry_type = "breaker block limit"

            if sweep_dir == "bearish":
                sl = round(sweep_extreme * 1.0002, 5)
                tp = round(eight_low, 5)
                log.trade("SHORT", entry, sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"eight_high": eight_high, "eight_low": eight_low,
                           "sweep_extreme": sweep_extreme,
                           "mss": True, "entry_type": entry_type})
            else:
                sl = round(sweep_extreme * 0.9998, 5)
                tp = round(eight_high, 5)
                log.trade("LONG", entry, sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"eight_high": eight_high, "eight_low": eight_low,
                           "sweep_extreme": sweep_extreme,
                           "mss": True, "entry_type": entry_type})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
