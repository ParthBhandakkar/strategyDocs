"""
Strategy: Gold Trading Strategy (High Winrate)
Source: Faiz SMC ("NEW Gold Trading Strategy That Works Everyday! (High Winrate)")
Video: http://www.youtube.com/watch?v=SF4_BAEz9jg

Core Concept:
  Gold. 5M session-based ranges. Push → pullback MSS defines range.
  Sweep of range extreme → MSS + close back in → auto block entry.
  3 trades max (1 per session: Asia, London, NY). Fib 0.5 partial,
  final TP at opposite range extreme.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "GoldHighWinrate"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M5"]


def get_session(hour):
    """Return session name based on NY hour."""
    if hour < 3 or hour >= 20:
        return "asia"
    elif 3 <= hour < 8:
        return "london"
    elif 8 <= hour < 17:
        return "ny"
    return None


def find_range_structure(bars: list, idx: int, lookback: int = 24):
    seg = bars[max(0, idx - lookback):idx + 1]
    if len(seg) < 6:
        return None

    highs = []
    lows = []
    for j in range(1, len(seg) - 1):
        if seg[j]["high"] > seg[j - 1]["high"] and seg[j]["high"] > seg[j + 1]["high"]:
            highs.append((j, seg[j]["high"]))
        if seg[j]["low"] < seg[j - 1]["low"] and seg[j]["low"] < seg[j + 1]["low"]:
            lows.append((j, seg[j]["low"]))

    if not highs or not lows:
        return None

    last_h = max(highs, key=lambda x: x[0])
    last_l = max(lows, key=lambda x: x[0])

    if last_h[0] > last_l[0]:
        r_high = last_h[1]
        for j in range(last_h[0], len(seg)):
            if seg[j]["low"] < last_l[1]:
                return (r_high, seg[j]["low"], "bullish")
        return (r_high, last_l[1], "bullish")
    if last_l[0] > last_h[0]:
        r_low = last_l[1]
        for j in range(last_l[0], len(seg)):
            if seg[j]["high"] > last_h[1]:
                return (seg[j]["high"], r_low, "bearish")
        return (last_h[1], r_low, "bearish")

    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m5_bars = get_bars(data_dir, symbol, "M5")
    if not m5_bars:
        print("No data found")
        return

    trades_taken = 0
    max_trades = 3
    sessions_used = set()
    state = "FIND_RANGE"
    range_high = 0.0
    range_low = 0.0
    range_dir = ""

    for i in range(20, len(m5_bars)):
        bar = m5_bars[i]
        ny = get_ny_time(bar["time"])
        session = get_session(ny.hour)

        if session is None:
            continue

        if trades_taken >= max_trades:
            break

        # ── State: FIND_RANGE ───────────────────────────────────────
        if state == "FIND_RANGE":
            structure = find_range_structure(m5_bars, i)
            if structure is None:
                continue

            range_high, range_low, range_dir = structure
            state = "WAIT_SWEEP"

            log.event(1, f"Range ({session.upper()} session)",
                      bar["time"], range_high, "M5",
                      f"Range: {range_high:.2f} - {range_low:.2f}")

        # ── State: WAIT_SWEEP ───────────────────────────────────────
        elif state == "WAIT_SWEEP":
            if range_dir == "bullish":
                if bar["low"] < range_low:
                    state = "WAIT_RETURN"
                    log.event(2, f"{session.upper()}: Range Low Swept",
                              bar["time"], bar["low"], "M5")
            else:
                if bar["high"] > range_high:
                    state = "WAIT_RETURN"
                    log.event(2, f"{session.upper()}: Range High Swept",
                              bar["time"], bar["high"], "M5")

        # ── State: WAIT_RETURN ──────────────────────────────────────
        elif state == "WAIT_RETURN":
            if range_dir == "bullish":
                if bar["close"] > range_low and bar["close"] > bar["open"]:
                    log.event(3, f"{session.upper()}: MSS + Return (Long)",
                              bar["time"], bar["close"], "M5")

                    entry = bar["close"]
                    sl = round(range_low * 0.9998, 5)
                    mid = round((range_high + range_low) / 2, 5)
                    tp = round(range_high, 5)

                    log.trade("LONG", entry, sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"range_high": range_high,
                               "range_low": range_low,
                               "mid_range": mid,
                               "session": session,
                               "trade_num": trades_taken + 1,
                               "management": "Fib 0.5 partial, TP at range high"})
                    trades_taken += 1
                    sessions_used.add(session)
                    state = "FIND_RANGE"
            else:
                if bar["close"] < range_high and bar["close"] < bar["open"]:
                    log.event(3, f"{session.upper()}: MSS + Return (Short)",
                              bar["time"], bar["close"], "M5")

                    entry = bar["close"]
                    sl = round(range_high * 1.0002, 5)
                    mid = round((range_high + range_low) / 2, 5)
                    tp = round(range_low, 5)

                    log.trade("SHORT", entry, sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"range_high": range_high,
                               "range_low": range_low,
                               "mid_range": mid,
                               "session": session,
                               "trade_num": trades_taken + 1,
                               "management": "Fib 0.5 partial, TP at range low"})
                    trades_taken += 1
                    sessions_used.add(session)
                    state = "FIND_RANGE"

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
