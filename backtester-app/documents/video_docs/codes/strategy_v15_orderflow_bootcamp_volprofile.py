"""
Strategy: Orderflow Boot Camp Lesson 1: Volume Profile
Source: Faiz SMC ("Orderflow Boot Camp Lesson 1: Volume Profile")
Video: https://www.youtube.com/watch?v=2cOo0oEPUPE

Core Concept:
  1) FRVP over a D-shape (balanced) consolidation range.
  2) Wait for break beyond VAH/VAL.
  3) Wait for consolidation outside VAH/VAL (value acceptance).
  4) Enter on clean break of secondary consolidation. Target 1:2 RR.
  If break fails to consolidate → expect reversal (antipodal).
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "OrderflowBootcampVolProfile"
SYMBOL = "NQ"
TIMEFRAMES = ["M1", "M5"]


def detect_dshape(profile: dict, tolerance: float = 0.15) -> bool:
    """Check if profile is D-shaped (symmetrical, POC near center)."""
    if not profile or profile["total_volume"] == 0:
        return False
    vah = profile["vah"]
    val = profile["val"]
    poc = profile["poc"]
    span = vah - val
    if span == 0:
        return False
    poc_position = (poc - val) / span
    # POC near center of range (0.35 - 0.65)
    return tolerance <= poc_position <= (1 - tolerance)


def find_consolidation(bars: list, lookback: int = 30) -> dict | None:
    """Find the most recent consolidation range using a simple range detection."""
    if len(bars) < lookback:
        return None
    seg = bars[-lookback:]
    high = max(b["high"] for b in seg)
    low = min(b["low"] for b in seg)
    avg_range = sum(b["high"] - b["low"] for b in seg) / len(seg)
    range_pct = (high - low) / (high + low) * 100 if high > 0 else 0

    # Consolidation: range is compact (< 0.5% for NQ)
    if range_pct > 0.5:
        return None

    return {"start": seg[0]["time"], "end": seg[-1]["time"],
            "high": high, "low": low, "avg_range": avg_range,
            "bars": seg}


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m1_bars = get_bars(data_dir, symbol, "M1")
    m5_bars = get_bars(data_dir, symbol, "M5")

    if not m1_bars:
        print("No data found")
        return

    # ── Step 1-3: Find D-shape consolidation and draw FRVP ─────────
    # Search for consolidation on M5 for context
    m5_consol = find_consolidation(m5_bars, 20) if m5_bars else None
    if not m5_consol:
        log.event(1, "No Consolidation Found", m1_bars[-1]["time"],
                  0, "M5", "No clear D-shape range identified.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # Draw profile over the consolidation
    profile = compute_volume_profile(m5_consol["bars"], row_size=1.0)

    if not detect_dshape(profile):
        log.event(1, "Non-D Profile (Skipped)", m5_consol["start"],
                  profile.get("poc", 0), "M5",
                  "Profile shape is not balanced D-shape.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    vah = profile["vah"]
    val = profile["val"]
    poc = profile["poc"]

    log.event(1, "D-Shape FRVP Identified", m5_consol["start"],
              poc, "M5",
              f"VAH={vah:.2f}, VAL={val:.2f}, POC={poc:.2f}")

    # ── State Machine on M1 ─────────────────────────────────────────
    state = "WAIT_BREAK"
    break_direction = None
    break_price = 0.0
    consol_outside = None
    trade_taken = False

    consol_start_idx = next(
        i for i, b in enumerate(m1_bars) if b["time"] >= m5_consol["end"]
    )

    for i in range(consol_start_idx + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 7 or ny.hour >= 16:
            continue
        if trade_taken:
            break

        # ── Step 4: Track breakout ────────────────────────────────
        if state == "WAIT_BREAK":
            if bar["close"] > vah:
                break_direction = "long"
                break_price = bar["high"]
                state = "WAIT_CONSOLIDATION"
                log.event(2, "Breakout Above VAH", bar["time"],
                          bar["close"], "M1",
                          f"Price closed above VAH={vah:.2f}")

            elif bar["close"] < val:
                break_direction = "short"
                break_price = bar["low"]
                state = "WAIT_CONSOLIDATION"
                log.event(2, "Breakout Below VAL", bar["time"],
                          bar["close"], "M1",
                          f"Price closed below VAL={val:.2f}")

        # ── Step 4: Wait for consolidation outside VAH/VAL ───────
        if state == "WAIT_CONSOLIDATION":
            lookback = m1_bars[max(0, i - 10):i + 1]

            if break_direction == "long":
                outside = all(b["low"] > vah for b in lookback)
                if outside:
                    ch = max(b["high"] for b in lookback)
                    cl = min(b["low"] for b in lookback)
                    # Check if there's a clear range
                    if ch - cl > 0:
                        consol_outside = {"high": ch, "low": cl}
                        state = "WAIT_BREAKOUT"
                        log.event(3, "Consolidation Above VAH (Value Accept)",
                                  bar["time"], bar["close"], "M1",
                                  f"Price consolidated outside VAH. "
                                  f"Range: {cl:.2f}-{ch:.2f}")
            else:
                outside = all(b["high"] < val for b in lookback)
                if outside:
                    ch = max(b["high"] for b in lookback)
                    cl = min(b["low"] for b in lookback)
                    if ch - cl > 0:
                        consol_outside = {"high": ch, "low": cl}
                        state = "WAIT_BREAKOUT"
                        log.event(3, "Consolidation Below VAL (Value Accept)",
                                  bar["time"], bar["close"], "M1",
                                  f"Price consolidated outside VAL. "
                                  f"Range: {cl:.2f}-{ch:.2f}")

        # ── Step 5: Execute on secondary breakout ─────────────────
        if state == "WAIT_BREAKOUT":
            if break_direction == "long" and bar["close"] > consol_outside["high"]:
                sl = round(val * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - consol_outside["low"]) * 2, 5)
                log.event(4, "Long Entry (Secondary Breakout)", bar["time"],
                          bar["close"], "M1",
                          f"Broke above consolidation={consol_outside['high']:.2f}")

                log.trade(
                    "LONG", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                    {"vah": vah, "val": val, "poc": poc,
                     "primary_break": break_price,
                     "secondary_consol_high": consol_outside["high"],
                     "secondary_consol_low": consol_outside["low"]}
                )
                trade_taken = True
                break

            elif break_direction == "short" and bar["close"] < consol_outside["low"]:
                sl = round(vah * 1.0002, 5)
                tp = round(bar["close"] - (consol_outside["high"] - bar["close"]) * 2, 5)
                log.event(4, "Short Entry (Secondary Breakout)", bar["time"],
                          bar["close"], "M1",
                          f"Broke below consolidation={consol_outside['low']:.2f}")

                log.trade(
                    "SHORT", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                    {"vah": vah, "val": val, "poc": poc,
                     "primary_break": break_price,
                     "secondary_consol_high": consol_outside["high"],
                     "secondary_consol_low": consol_outside["low"]}
                )
                trade_taken = True
                break

            # Antipodal reversal: if price returns inside VAH/VAL after break
            if break_direction == "long" and bar["close"] < vah:
                log.event(3, "Antipodal Reversal Signal", bar["time"],
                          bar["close"], "M1",
                          "Price rejected outside VAH, returned inside. "
                          "Expect reversal to VAL.")
                # Don't trade antipodal, just log

            elif break_direction == "short" and bar["close"] > val:
                log.event(3, "Antipodal Reversal Signal", bar["time"],
                          bar["close"], "M1",
                          "Price rejected outside VAL, returned inside. "
                          "Expect reversal to VAH.")

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
