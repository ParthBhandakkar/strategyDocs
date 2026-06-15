"""
Strategy: Midas Model (5M Timeframe)
Source: Faiz SMC ("Easy Gold Trading Strategy That Works Every Time!")
Video: http://www.youtube.com/watch?v=6xbLspSa86A

Core Concept:
  Gold only. Asian session (post-8PM NY). 5M liquidity sweep → define
  dealing range → identify FVGs within range → wait for price to close
  above/below ALL FVGs (inversion). Max 2 trades per session.
  BE at nearest liquidity. 1:1.5-1:2 target. Silver SMT optional.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "MidasModel5M"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M5"]


def detect_liquidity_sweep(bars: list, idx: int, lookback: int = 6):
    """Check if bar at idx sweeps a recent swing extreme."""
    seg = bars[max(0, idx - lookback):idx + 1]
    seg_high = max(b["high"] for b in seg)
    seg_low = min(b["low"] for b in seg)

    bar = bars[idx]
    if bar["high"] >= seg_high and bar["low"] <= seg_low:
        return "both", seg_high, seg_low
    if bar["high"] > max(b["high"] for b in seg[:-1]) and seg[-2]["high"] < seg[-1]["high"]:
        return "buy_side", seg_high, seg_low
    if bar["low"] < min(b["low"] for b in seg[:-1]) and seg[-2]["low"] > seg[-1]["low"]:
        return "sell_side", seg_high, seg_low
    return None, seg_high, seg_low


def all_fvgs_inversed(bars: list, fvgs: list, bar_idx: int) -> tuple:
    """Check if price at bar_idx closes past all FVGs. Returns (bool, direction)."""
    bar = bars[bar_idx]
    bullish_count = sum(1 for f in fvgs if f["direction"] == "bullish")
    bearish_count = sum(1 for f in fvgs if f["direction"] == "bearish")

    if bearish_count > bullish_count:
        # Expect bearish inversion
        if all(bar["close"] < f["bottom"] for f in fvgs if f["direction"] == "bearish") and bar["close"] < bar["open"]:
            return True, "bearish"
    elif bullish_count > bearish_count:
        if all(bar["close"] > f["top"] for f in fvgs if f["direction"] == "bullish") and bar["close"] > bar["open"]:
            return True, "bullish"
    else:
        # Equal split — require all inversed in one direction
        if all(bar["close"] < f["bottom"] for f in fvgs) and bar["close"] < bar["open"]:
            return True, "bearish"
        if all(bar["close"] > f["top"] for f in fvgs) and bar["close"] > bar["open"]:
            return True, "bullish"
    return False, ""


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m5_bars = get_bars(data_dir, symbol, "M5")
    if not m5_bars:
        print("No data found")
        return

    trades_taken = 0
    max_trades = 2
    state = "WAIT_SWEEP"
    dealing_high = 0.0
    dealing_low = 0.0
    sweep_index = 0

    for i in range(10, len(m5_bars)):
        bar = m5_bars[i]
        ny = get_ny_time(bar["time"])

        # Asian session only (post 8PM NY)
        if not (ny.hour >= 20 or ny.hour < 0):
            continue

        if trades_taken >= max_trades:
            log.event(0, "Max trades reached for session", bar["time"], 0, "M5")
            break

        # ── State: WAIT_SWEEP ───────────────────────────────────────
        if state == "WAIT_SWEEP":
            sweep_type, sw_high, sw_low = detect_liquidity_sweep(m5_bars, i)

            if sweep_type is None:
                continue

            sweep_index = i
            dealing_high = sw_high
            dealing_low = sw_low
            state = "WAIT_FVG_INVERSION"

            log.event(1, "5M Liquidity Sweep Detected", bar["time"],
                      bar["close"], "M5",
                      f"Type={sweep_type}, Range={dealing_high:.2f}-{dealing_low:.2f}")

        # ── State: WAIT_FVG_INVERSION ───────────────────────────────
        elif state == "WAIT_FVG_INVERSION":
            seg = m5_bars[sweep_index:i + 1]
            seg_fvgs = detect_fvg(seg)

            # Filter to FVGs within the dealing range
            range_fvgs = [
                f for f in seg_fvgs
                if f["top"] <= dealing_high and f["bottom"] >= dealing_low
            ]

            if not range_fvgs:
                # Check if sweep has expired, or if a new sweep occurs
                if i > sweep_index + 12:
                    state = "WAIT_SWEEP"
                    log.event(2, "No FVGs in range, resetting", bar["time"],
                              bar["close"], "M5")
                continue

            inversed, inv_dir = all_fvgs_inversed(seg, range_fvgs, len(seg) - 1)

            if not inversed:
                if i > sweep_index + 12:
                    state = "WAIT_SWEEP"
                    log.event(2, "Inversion not confirmed, resetting", bar["time"],
                              bar["close"], "M5")
                continue

            log.event(3, f"FVG Inversion Confirmed ({inv_dir.upper()})",
                      bar["time"], bar["close"], "M5",
                      f"FVGs inversed in range: {len(range_fvgs)}")

            if inv_dir == "bullish":
                sl = round(bar["low"] * 0.9998, 5)
                # Target 1:1.5 to 1:2
                tp = round(bar["close"] + (bar["close"] - sl) * 1.5, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"dealing_high": dealing_high,
                           "dealing_low": dealing_low,
                           "fvgs_inversed": len(range_fvgs),
                           "trade_num": trades_taken + 1,
                           "max_trades": max_trades,
                           "management": "BE at nearest liquidity, 1:1.5-1:2 target"})
            else:
                sl = round(bar["high"] * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 1.5, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"dealing_high": dealing_high,
                           "dealing_low": dealing_low,
                           "fvgs_inversed": len(range_fvgs),
                           "trade_num": trades_taken + 1,
                           "max_trades": max_trades,
                           "management": "BE at nearest liquidity, 1:1.5-1:2 target"})

            trades_taken += 1
            state = "WAIT_SWEEP"

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
