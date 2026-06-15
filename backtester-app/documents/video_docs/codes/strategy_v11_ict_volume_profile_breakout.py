"""
Strategy: ICT + Volume Profile Breakout Strategy
Source: Faiz SMC ("ICT + Volume Profile = Insane Profit")
Video: https://www.youtube.com/watch?v=wmcoNjbUxyI

Core Concept:
  Draw FRVP from 18:00-08:55 NY on M5 chart.
  Scenario A (Within Balance): Price between VAH/VAL → wait for break outside.
  Scenario B (Outside Balance): Price already outside → use directly.
  Failed Auction: Close outside → close back inside → enter at retest or FVG/OB.
  Breakout: Close outside → consolidate → break consolidation → enter.
  Max 2 trades/day, opposite directions.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "ICTVolumeProfileBreakout"
SYMBOL = "NQ"
TIMEFRAMES = ["M5"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    bars_m5 = get_bars(data_dir, symbol, "M5")
    if not bars_m5:
        print("No data found")
        return

    # ── Step 1 & 2: FRVP from 18:00 to 08:55 NY ──────────────────────
    premkt_bars = [
        b for b in bars_m5
        if get_ny_time(b["time"]).hour >= 18 or
        get_ny_time(b["time"]).hour < 9 or
        (get_ny_time(b["time"]).hour == 9 and get_ny_time(b["time"]).minute < 55)
    ]

    profile = compute_volume_profile(premkt_bars, row_size=1.0) if premkt_bars else None

    if not profile:
        log.event(1, "Profile Build Failed", bars_m5[-1]["time"], 0, "M5",
                  "Insufficient pre-market data from 18:00-08:55.")
        return

    vah = profile["vah"]
    val = profile["val"]
    poc = profile["poc"]

    log.event(
        1, "Pre-Market FRVP (18:00-08:55)", premkt_bars[0]["time"], poc, "M5",
        f"VAH={vah:.2f}, VAL={val:.2f}, POC={poc:.2f}"
    )

    # ── Step 3: Identify initial position ────────────────────────────
    ny_855_bars = [
        b for b in bars_m5
        if get_ny_time(b["time"]).hour == 8 and get_ny_time(b["time"]).minute >= 55
    ]
    last_before_9 = ny_855_bars[-1] if ny_855_bars else bars_m5[-1]

    if last_before_9["close"] > vah:
        initial_position = "above_VAH"
        log.event(2, "Scenario B: Price Already Above VAH", last_before_9["time"],
                  last_before_9["close"], "M5", "Price above VAH at 08:55.")
    elif last_before_9["close"] < val:
        initial_position = "below_VAL"
        log.event(2, "Scenario B: Price Already Below VAL", last_before_9["time"],
                  last_before_9["close"], "M5", "Price below VAL at 08:55.")
    else:
        initial_position = "within_balance"
        log.event(2, "Scenario A: Price Within Balance", last_before_9["time"],
                  last_before_9["close"], "M5", "Price between VAH and VAL. Wait for break.")

    # ── State Machine ────────────────────────────────────────────────
    state = "WAIT_BREAK"
    break_direction = None
    break_candle_high = 0.0
    break_candle_low = 0.0
    consolidation_high = 0.0
    consolidation_low = 0.0
    trade_taken = False
    daily_trade_count = 0
    last_trade_date = None

    for i in range(1, len(bars_m5)):
        bar = bars_m5[i]
        ny = get_ny_time(bar["time"])

        # Skip before 9:00 AM (profile window just ended)
        if ny.hour < 9:
            continue

        if ny.hour >= 16:
            break

        if trade_taken:
            break

        # Reset daily limit
        if last_trade_date != ny.date():
            daily_trade_count = 0
            last_trade_date = ny.date()

        if daily_trade_count >= 2:
            log.event(5, "Daily Trade Limit (2) Reached", bar["time"], bar["close"], "M5")
            break

        # ── Step 4a: Failed Auction Setup ────────────────────────────
        if state == "WAIT_BREAK":
            # Look for break outside value area
            if bar["high"] > vah and bar["close"] > vah:
                break_direction = "high"
                break_candle_high = bar["high"]
                break_candle_low = bar["low"]
                log.event(3, "Break Above VAH", bar["time"], bar["high"], "M5",
                          f"Price closed above VAH={vah:.2f}. Monitoring for failed auction.")
                # Wait for next candle to see if it closes back inside
                continue

            elif bar["low"] < val and bar["close"] < val:
                break_direction = "low"
                break_candle_high = bar["high"]
                break_candle_low = bar["low"]
                log.event(3, "Break Below VAL", bar["time"], bar["low"], "M5",
                          f"Price closed below VAL={val:.2f}. Monitoring for failed auction.")
                continue

            if break_direction:
                state = "WAIT_FAILED"

        elif state == "WAIT_FAILED":
            # Check if price closes back inside value area (failed auction)
            if break_direction == "high" and bar["close"] < vah:
                # Failed auction at VAH → short
                break_direction = None
                daily_trade_count += 1
                entry = bar["close"]

                # Find adjacent FVG for entry optimization
                recent_bars = bars_m5[max(0, i - 10):i + 1]
                near_fvgs = detect_fvg(recent_bars)

                sl = round(break_candle_high * 1.0003, 5)
                tp = round(val, 5)

                log.event(4, "Failed Auction Confirmed at VAH", bar["time"],
                          bar["close"], "M5",
                          "Price closed back inside value. Short entry.")

                log.trade(
                    "SHORT", entry, sl, tp, bar["time"], symbol, STRATEGY_NAME,
                    {"vah": vah, "val": val, "poc": poc,
                     "break_high": break_candle_high,
                     "setup_type": "failed_auction",
                     "nearby_fvgs": len(near_fvgs)}
                )
                trade_taken = True
                break

            elif break_direction == "low" and bar["close"] > val:
                # Failed auction at VAL → long
                break_direction = None
                daily_trade_count += 1
                entry = bar["close"]

                recent_bars = bars_m5[max(0, i - 10):i + 1]
                near_fvgs = detect_fvg(recent_bars)

                sl = round(break_candle_low * 0.9997, 5)
                tp = round(poc, 5)

                log.event(4, "Failed Auction Confirmed at VAL", bar["time"],
                          bar["close"], "M5",
                          "Price closed back inside value. Long entry.")

                log.trade(
                    "LONG", entry, sl, tp, bar["time"], symbol, STRATEGY_NAME,
                    {"vah": vah, "val": val, "poc": poc,
                     "break_low": break_candle_low,
                     "setup_type": "failed_auction",
                     "nearby_fvgs": len(near_fvgs)}
                )
                trade_taken = True
                break

            # Check for breakout model: consolidation outside value area
            if break_direction == "high" and bar["high"] > vah:
                # Look for consolidation above VAH
                seg = bars_m5[max(0, i - 6):i + 1]
                if all(b["low"] > vah for b in seg):
                    consolidation_high = max(b["high"] for b in seg)
                    consolidation_low = min(b["low"] for b in seg)

                    if bar["close"] > consolidation_high and bar["close"] > vah:
                        daily_trade_count += 1
                        log.event(4, "Breakout Above VAH Confirmed", bar["time"],
                                  bar["close"], "M5",
                                  "Consolidated above VAH and broke out. Long.")

                        sl = round(consolidation_low * 0.9998, 5)
                        tp = round(bar["close"] + (bar["close"] - consolidation_low) * 2, 5)

                        log.trade(
                            "LONG", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                            {"vah": vah, "val": val, "poc": poc,
                             "setup_type": "breakout",
                             "consolidation_high": consolidation_high,
                             "consolidation_low": consolidation_low}
                        )
                        trade_taken = True
                        break

            elif break_direction == "low" and bar["low"] < val:
                seg = bars_m5[max(0, i - 6):i + 1]
                if all(b["high"] < val for b in seg):
                    consolidation_high = max(b["high"] for b in seg)
                    consolidation_low = min(b["low"] for b in seg)

                    if bar["close"] < consolidation_low and bar["close"] < val:
                        daily_trade_count += 1
                        log.event(4, "Breakout Below VAL Confirmed", bar["time"],
                                  bar["close"], "M5",
                                  "Consolidated below VAL and broke out. Short.")

                        sl = round(consolidation_high * 1.0002, 5)
                        tp = round(bar["close"] - (consolidation_high - bar["close"]) * 2, 5)

                        log.trade(
                            "SHORT", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                            {"vah": vah, "val": val, "poc": poc,
                             "setup_type": "breakout",
                             "consolidation_high": consolidation_high,
                             "consolidation_low": consolidation_low}
                        )
                        trade_taken = True
                        break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
