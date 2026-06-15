"""
Strategy: Volume Profile and Orderflow Reversal Strategy
Source: Faiz SMC ("Volume Profile + Orderflow = Profit")
Video: https://www.youtube.com/watch?v=eap7vH0zOQ8

Core Concept:
  Uses Overnight Volume Profile (18:00-09:30 NY) + 1-min orderflow absorption.
  Short: Price breaks above overnight VAH → buyer absorption at wicks →
         1-min close below close proximity order box → short to POC/VAL
  Long: Price breaks below overnight VAL → seller absorption at wicks →
        1-min close above close proximity order box → long to POC/VAH

  Key Rule: If price hits overnight POC before entry triggers, setup is INVALID.
  Close Proximity Orders = the cluster of aggressive orders that drove the breakout.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "VolumeProfileOrderflowReversal"
SYMBOL = "NQ"
TIMEFRAMES = ["M1", "M5"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    bars_m1 = get_bars(data_dir, symbol, "M1")
    bars_m5 = get_bars(data_dir, symbol, "M5")

    if not bars_m1:
        print("No data found")
        return

    # ── Step 1: Build Overnight Volume Profile (18:00 to 09:30 NY) ──
    overnight_bars = [
        b for b in bars_m5
        if get_ny_time(b["time"]).hour >= 18 or get_ny_time(b["time"]).hour < 9 or
        (get_ny_time(b["time"]).hour == 9 and get_ny_time(b["time"]).minute < 30)
    ]

    profile = compute_volume_profile(overnight_bars, row_size=1.0) if overnight_bars else None

    if not profile:
        log.event(1, "Overnight Profile - Fallback", bars_m1[0]["time"], 0, "M5",
                  "Insufficient overnight data for profile. Using full-range estimate.")
        highs = [b["high"] for b in bars_m5[-100:]] if bars_m5 else [b["high"] for b in bars_m1[-100:]]
        lows = [b["low"] for b in bars_m5[-100:]] if bars_m5 else [b["low"] for b in bars_m1[-100:]]
        vah = max(highs)
        val = min(lows)
        poc = (vah + val) / 2
    else:
        vah = profile["vah"]
        val = profile["val"]
        poc = profile["poc"]
        log.event(
            1, "Overnight Volume Profile Built (18:00-09:30)", bars_m1[0]["time"], poc, "M5",
            f"VAH={vah:.2f}, VAL={val:.2f}, POC={poc:.2f}, Volume={profile['total_volume']:.0f}"
        )

    # VWAP calculation from overnight
    ovn_vwap = sum(b["close"] * b.get("volume", 1) for b in overnight_bars) / \
        max(sum(b.get("volume", 1) for b in overnight_bars), 1) if overnight_bars else poc

    log.event(1, "Overnight VWAP", bars_m1[0]["time"], ovn_vwap, "M1",
              f"VWAP={ovn_vwap:.2f}")

    # ── State Machine ───────────────────────────────────────────────
    # Two independent state tracks: one for short, one for long
    state = "MONITOR"
    close_proximity_box_high = 0.0
    close_proximity_box_low = 0.0
    break_direction = None
    breakout_candle_high = 0.0
    breakout_candle_low = 0.0
    poc_hit_before_entry = False
    trade_taken = False

    for i in range(3, len(bars_m1)):
        bar = bars_m1[i]
        prev = bars_m1[i - 1]
        ny = get_ny_time(bar["time"])

        # Only trade after 9:30 AM NY
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue

        if ny.hour >= 16:
            break

        if trade_taken:
            break

        recent_10 = bars_m1[max(0, i - 10):i + 1]

        # ── Check POC Invalidation Rule ─────────────────────────────
        # If price hits the overnight POC before our entry triggers, cancel setup
        if state == "WAIT_CLOSE_BOX_SHORT" or state == "WAIT_CLOSE_BOX_LONG":
            if bar["low"] <= poc <= bar["high"]:
                poc_hit_before_entry = True
                log.event(
                    4, "POC Invalidation - Setup Cancelled", bar["time"],
                    poc, "M1",
                    "Price hit overnight POC before entry trigger. Aborting setup."
                )
                state = "MONITOR"
                continue

        # ── Monitor for breakout of overnight VAH or VAL ─────────────
        if state == "MONITOR":
            # Check short setup: price breaks above VAH
            if bar["close"] > vah and bar["close"] > bar["open"]:
                # This is a breakout above VAH - look for buyer absorption
                # Check if previous candle(s) showed bullish absorption at the wick
                for lookback in range(max(3, i - 5), i + 1):
                    cb = bars_m1[lookback]
                    body = abs(cb["close"] - cb["open"])
                    upper_wick = cb["high"] - max(cb["close"], cb["open"])

                    # Absorption signal: bullish candle reaching above VAH with upper wick
                    if cb["high"] >= vah and upper_wick > body * 0.3:
                        avg_vol = sum(b.get("volume", 0) for b in bars_m1[max(0, lookback - 20):lookback]) / 20
                        if avg_vol > 0 and cb.get("volume", 0) > avg_vol * 1.2:
                            # Found aggressive buying with sign of absorption
                            close_proximity_box_high = max(
                                b["high"] for b in recent_10[-5:]
                            )
                            close_proximity_box_low = min(
                                b["low"] for b in recent_10[-5:]
                            )
                            breakout_candle_high = cb["high"]
                            break_direction = "short"
                            state = "WAIT_CLOSE_BOX_SHORT"
                            log.event(
                                2, "Buyer Absorption Above Overnight VAH", cb["time"],
                                cb["high"], "M1",
                                f"Aggressive buyers at wick. Volume={cb['volume']:.0f}, "
                                f"Upper wick={upper_wick:.2f}. Close proximity box drawn: "
                                f"{close_proximity_box_low:.2f}-{close_proximity_box_high:.2f}"
                            )
                            break

            # Check long setup: price breaks below VAL
            elif bar["close"] < val and bar["close"] < bar["open"]:
                for lookback in range(max(3, i - 5), i + 1):
                    cb = bars_m1[lookback]
                    body = abs(cb["close"] - cb["open"])
                    lower_wick = min(cb["close"], cb["open"]) - cb["low"]

                    if cb["low"] <= val and lower_wick > body * 0.3:
                        avg_vol = sum(b.get("volume", 0) for b in bars_m1[max(0, lookback - 20):lookback]) / 20
                        if avg_vol > 0 and cb.get("volume", 0) > avg_vol * 1.2:
                            close_proximity_box_high = max(
                                b["high"] for b in recent_10[-5:]
                            )
                            close_proximity_box_low = min(
                                b["low"] for b in recent_10[-5:]
                            )
                            breakout_candle_low = cb["low"]
                            break_direction = "long"
                            state = "WAIT_CLOSE_BOX_LONG"
                            log.event(
                                2, "Seller Absorption Below Overnight VAL", cb["time"],
                                cb["low"], "M1",
                                f"Aggressive sellers at wick. Volume={cb['volume']:.0f}, "
                                f"Lower wick={lower_wick:.2f}. Close proximity box drawn: "
                                f"{close_proximity_box_low:.2f}-{close_proximity_box_high:.2f}"
                            )
                            break

        # ── Step 4: Short Execution - Wait for close below close proximity box ──
        elif state == "WAIT_CLOSE_BOX_SHORT":
            if bar["close"] < close_proximity_box_low:
                # Bearish candle closed below support = support turned resistance
                log.event(
                    3, "Close Proximity Box Broken - Short Trigger", bar["time"],
                    bar["close"], "M1",
                    f"1-min candle closed below box low={close_proximity_box_low:.2f}. "
                    f"Support turned resistance."
                )

                sl = round(close_proximity_box_high * 1.0002, 5)
                tp = round(val, 5)

                log.trade(
                    "SHORT", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                    {"box_high": close_proximity_box_high,
                     "box_low": close_proximity_box_low,
                     "overnight_vah": vah,
                     "overnight_poc": poc,
                     "setup_type": "VAH_Reversal_Short"}
                )
                trade_taken = True
                log.event(5, "Trade Executed - Short", bar["time"], bar["close"], "M1",
                          f"SL={sl:.2f}, TP={tp:.2f}")
                break

            # If price fails to break and just keeps going up, reset
            if bar["high"] > close_proximity_box_high * 1.002:
                state = "MONITOR"
                log.event(3, "Breakout Continued - Reset", bar["time"], bar["high"], "M1",
                          "Price continued upward past close proximity box. Setup invalid.")

        # ── Step 4: Long Execution - Wait for close above close proximity box ──
        elif state == "WAIT_CLOSE_BOX_LONG":
            if bar["close"] > close_proximity_box_high and bar["close"] > bar["open"]:
                log.event(
                    3, "Close Proximity Box Broken - Long Trigger", bar["time"],
                    bar["close"], "M1",
                    f"Bullish 1-min candle closed above box high={close_proximity_box_high:.2f}. "
                    f"Resistance turned support."
                )

                sl = round(close_proximity_box_low * 0.9998, 5)
                tp = round(poc, 5)

                log.trade(
                    "LONG", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                    {"box_high": close_proximity_box_high,
                     "box_low": close_proximity_box_low,
                     "overnight_val": val,
                     "overnight_poc": poc,
                     "setup_type": "VAL_Reversal_Long"}
                )
                trade_taken = True
                log.event(5, "Trade Executed - Long", bar["time"], bar["close"], "M1",
                          f"SL={sl:.2f}, TP={tp:.2f}")
                break

            if bar["low"] < close_proximity_box_low * 0.998:
                state = "MONITOR"
                log.event(3, "Breakout Continued - Reset", bar["time"], bar["low"], "M1",
                          "Price continued downward past close proximity box. Setup invalid.")

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
