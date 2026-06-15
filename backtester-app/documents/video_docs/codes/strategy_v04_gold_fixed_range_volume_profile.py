"""
Strategy: Gold Fixed Range Volume Profile Scalping Strategy
Source: Faiz SMC ("The Easiest Gold Volume Profile Trading Strategy That Works!")
Video: https://www.youtube.com/watch?v=LsC2IokcYpc

Core Concept:
  Gold-only (XAUUSD) on 5-min chart. Draw FRVP from London session (3:00-7:00 AM NY).
  Classify shape: D (balanced → failed auction), P (bullish → breakout), B (bearish → breakout).
  Failed Auction: Price breaks VAH/VAL, then closes back inside → enter toward POC.
  Breakout: Price breaks outside and consolidates → break of consolidation = momentum entry.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "GoldFixedRangeVolumeProfile"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M5"]


def classify_profile_shape(profile: dict) -> str:
    """Classify the volume profile shape: D, P, or b."""
    if not profile:
        return "D"
    va_range = profile["vah"] - profile["val"]
    if va_range <= 0:
        return "D"
    poc_position = (profile["poc"] - profile["val"]) / va_range
    if poc_position > 0.6:
        return "P"
    elif poc_position < 0.4:
        return "b"
    return "D"


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    bars_m5 = get_bars(data_dir, symbol, "M5")

    if not bars_m5:
        print("No M5 data found")
        return

    # ── Step 1 & 2: FRVP from London Session (3:00-7:00 AM NY) ──────
    london_bars = [
        b for b in bars_m5
        if 3 <= get_ny_time(b["time"]).hour < 7
    ]

    if len(london_bars) < 10:
        log.event(1, "London Session - Insufficient Data", bars_m5[-1]["time"],
                  0, "M5", "Need at least 10 bars from 3:00-7:00 AM NY. Using latest bars.")
        london_bars = bars_m5[-48:] if len(bars_m5) >= 48 else bars_m5

    profile = compute_volume_profile(london_bars, row_size=0.10)
    if not profile:
        log.event(1, "Profile Build Failed", bars_m5[-1]["time"], 0, "M5",
                  "Could not compute volume profile.")
        return

    vah = profile["vah"]
    val = profile["val"]
    poc = profile["poc"]
    shape = classify_profile_shape(profile)

    log.event(
        1, f"London FRVP Built (3:00-7:00 AM)", london_bars[0]["time"], poc, "M5",
        f"Shape={shape}, VAH={vah:.2f}, VAL={val:.2f}, POC={poc:.2f}"
    )

    # ── State Machine ────────────────────────────────────────────────
    state = "WAIT_7AM"
    break_direction = None
    break_high = 0.0
    break_low = 0.0
    setup_type = None  # "failed_auction" or "breakout"
    trade_taken = False
    daily_short = 0
    daily_long = 0
    last_trade_date = None

    for i in range(1, len(bars_m5)):
        bar = bars_m5[i]
        ny = get_ny_time(bar["time"])

        # Reset daily counters
        if last_trade_date != ny.date():
            daily_short = 0
            daily_long = 0
            last_trade_date = ny.date()

        # Skip before 7:00 AM when profile window completes
        if ny.hour < 7:
            continue

        if trade_taken:
            break

        # Max 2 trades/day, one per direction
        if daily_short >= 1 and daily_long >= 1:
            log.event(5, "Daily Limit Reached", bar["time"], bar["close"], "M5",
                      "Two trades done (one each direction). Stopping.")
            break

        # ── Step 3: Analyze Shape and Choose Strategy ────────────────
        if state == "WAIT_7AM":
            # Determine initial bias from shape
            if shape == "P":
                # Bullish bias: prioritize breakouts above VAH
                # Also watch for failed auctions if D-shape behavior
                pass
            elif shape == "b":
                # Bearish bias: prioritize breakouts below VAL
                pass
            # D-shape: failed auction setups preferred
            state = "MONITOR"

        # ── Step 4: Failed Auction Setup ─────────────────────────────
        if state == "MONITOR" or state == "WAIT_FAILED_RETURN":
            # Check if price breaks outside value area
            above_vah = bar["high"] > vah and bar["close"] > vah
            below_val = bar["low"] < val and bar["close"] < val

            if state == "MONITOR":
                if above_vah and daily_short < 1:
                    break_direction = "high"
                    break_high = bar["high"]
                    state = "WAIT_FAILED_RETURN"
                    log.event(
                        2, "Break Above VAH - Monitoring for Failed Auction", bar["time"],
                        bar["high"], "M5",
                        f"Price closed above VAH={vah:.2f}. "
                        f"Need close back below to trigger short."
                    )
                elif below_val and daily_long < 1:
                    break_direction = "low"
                    break_low = bar["low"]
                    state = "WAIT_FAILED_RETURN"
                    log.event(
                        2, "Break Below VAL - Monitoring for Failed Auction", bar["time"],
                        bar["low"], "M5",
                        f"Price closed below VAL={val:.2f}. "
                        f"Need close back above to trigger long."
                    )

            elif state == "WAIT_FAILED_RETURN":
                # Look for close back inside value area
                if break_direction == "high" and bar["close"] < vah:
                    # Failed auction at VAH → short
                    setup_type = "failed_auction"
                    sl = round(break_high + (break_high * 0.0003), 5)
                    tp = round(poc, 5)

                    log.event(
                        3, "Failed Auction at VAH Confirmed", bar["time"],
                        bar["close"], "M5",
                        f"Price closed back below VAH={vah:.2f} after breaking above. "
                        f"Bearish reversal confirmed."
                    )

                    log.trade(
                        "SHORT", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                        {"shape": shape, "vah": vah, "val": val, "poc": poc,
                         "setup_type": setup_type, "trade_number": daily_short + 1}
                    )
                    daily_short += 1
                    trade_taken = True
                    log.event(5, "Trade Executed - Failed Auction Short", bar["time"],
                              bar["close"], "M5",
                              f"Entry={bar['close']:.2f}, SL={sl:.2f}, TP={tp:.2f}")
                    break

                elif break_direction == "low" and bar["close"] > val:
                    # Failed auction at VAL → long
                    setup_type = "failed_auction"
                    sl = round(break_low - (break_low * 0.0003), 5)
                    tp = round(poc, 5)

                    log.event(
                        3, "Failed Auction at VAL Confirmed", bar["time"],
                        bar["close"], "M5",
                        f"Price closed back above VAL={val:.2f} after breaking below. "
                        f"Bullish reversal confirmed."
                    )

                    log.trade(
                        "LONG", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                        {"shape": shape, "vah": vah, "val": val, "poc": poc,
                         "setup_type": setup_type, "trade_number": daily_long + 1}
                    )
                    daily_long += 1
                    trade_taken = True
                    log.event(5, "Trade Executed - Failed Auction Long", bar["time"],
                              bar["close"], "M5",
                              f"Entry={bar['close']:.2f}, SL={sl:.2f}, TP={tp:.2f}")
                    break

                # POC Invalidation Rule: if price hits POC before entry, cancel
                if bar["low"] <= poc <= bar["high"]:
                    log.event(
                        4, "POC Hit - Failed Auction Cancelled", bar["time"],
                        poc, "M5",
                        "Price hit POC before entry trigger. Setup invalid."
                    )
                    state = "MONITOR"
                    continue

        # ── Step 5: Breakout Setup (P-shape or b-shape preferred) ────
        if not trade_taken and state in ("MONITOR", "WAIT_BREAKOUT"):
            # Look for consolidation outside value area
            lookback = 12
            if i >= lookback:
                recent = bars_m5[max(0, i - lookback):i + 1]
                all_above_vah = all(b["low"] > vah for b in recent)
                all_below_val = all(b["high"] < val for b in recent)

                if all_above_vah and shape in ("P", "D") and daily_long < 1:
                    # Consolidation above VAH → breakout long
                    con_high = max(b["high"] for b in recent)
                    con_low = min(b["low"] for b in recent)

                    if bar["close"] > con_high and bar["close"] > vah:
                        setup_type = "breakout"
                        sl = round(con_low - (con_low * 0.0003), 5)
                        tp = round(bar["close"] + (bar["close"] - con_low) * 2, 5)

                        log.event(
                            2, "Bullish Breakout Above VAH", bar["time"],
                            bar["close"], "M5",
                            f"Consolidation above VAH={vah:.2f} broken. "
                            f"New value acceptance confirmed."
                        )
                        log.event(3, "Breakout Entry Confirmed", bar["time"],
                                  bar["close"], "M5")

                        log.trade(
                            "LONG", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                            {"shape": shape, "vah": vah, "val": val, "poc": poc,
                             "setup_type": setup_type, "consolidation_low": con_low,
                             "consolidation_high": con_high}
                        )
                        daily_long += 1
                        trade_taken = True
                        log.event(5, "Trade Executed - Breakout Long", bar["time"],
                                  bar["close"], "M5")
                        break

                elif all_below_val and shape in ("b", "D") and daily_short < 1:
                    # Consolidation below VAL → breakout short
                    con_high = max(b["high"] for b in recent)
                    con_low = min(b["low"] for b in recent)

                    if bar["close"] < con_low and bar["close"] < val:
                        setup_type = "breakout"
                        sl = round(con_high + (con_high * 0.0003), 5)
                        tp = round(bar["close"] - (con_high - bar["close"]) * 2, 5)

                        log.event(
                            2, "Bearish Breakout Below VAL", bar["time"],
                            bar["close"], "M5",
                            f"Consolidation below VAL={val:.2f} broken. "
                            f"New value acceptance confirmed."
                        )
                        log.event(3, "Breakout Entry Confirmed", bar["time"],
                                  bar["close"], "M5")

                        log.trade(
                            "SHORT", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                            {"shape": shape, "vah": vah, "val": val, "poc": poc,
                             "setup_type": setup_type, "consolidation_low": con_low,
                             "consolidation_high": con_high}
                        )
                        daily_short += 1
                        trade_taken = True
                        log.event(5, "Trade Executed - Breakout Short", bar["time"],
                                  bar["close"], "M5")
                        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
