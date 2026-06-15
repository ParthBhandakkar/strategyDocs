"""
Strategy: Orderflow and Volume Profile Day Trading Strategy
Source: Faiz SMC ("How I Made $14,068 Day Trading With Orderflow")
Video: https://www.youtube.com/watch?v=yvcqeXnghDc

Core Concept:
  Uses 1-minute chart + daily volume profile to spot institutional absorption.
  Two setups:
    1) Short: Buyer absorption at VAH/POC → 1-min close below absorption cluster → TP at VAL
    2) Long: Seller absorption at VAL (discount zone) → 1-min close above absorption cluster → TP at VWAP

    Absorption = heavy volume traded at candle wicks without price follow-through,
    signaling institutional limit orders soaking up aggressive retail flow.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "OrderflowVolumeProfileDay"
SYMBOL = "NQ"
TIMEFRAMES = ["M1", "M5"]


def detect_absorption_at_wick(
    bar: dict,
    prev_bars: list[dict],
    direction: str,
    volume_threshold: float = 1.5
) -> bool:
    """
    Detect absorption at candle wicks.
    For bullish absorption (short setup):
      - Bullish candle (close > open)
      - Long upper wick (high - close > close - open)
      - Volume above average (threshold * avg_volume)
      - Next candle(s) fail to follow through upward

    For bearish absorption (long setup):
      - Bearish candle (close < open)
      - Long lower wick (low - open > open - close ??? actually low < open, so open - low > open - close)
      - Volume above average
      - Next candle(s) fail to follow through downward
    """
    if not prev_bars:
        return False

    avg_volume = sum(b.get("volume", 0) for b in prev_bars[-20:]) / max(len(prev_bars[-20:]), 1)
    if avg_volume == 0:
        return False

    body = abs(bar["close"] - bar["open"])
    wick_high = bar["high"] - max(bar["close"], bar["open"])
    wick_low = min(bar["close"], bar["open"]) - bar["low"]

    volume_ok = bar.get("volume", 0) > avg_volume * volume_threshold

    if direction == "bullish_absorption":
        # Bullish candle with long upper wick and high volume = buyers getting absorbed
        is_bullish = bar["close"] > bar["open"]
        has_upper_wick = wick_high > body * 0.5
        return is_bullish and has_upper_wick and volume_ok

    elif direction == "bearish_absorption":
        # Bearish candle with long lower wick and high volume = sellers getting absorbed
        is_bearish = bar["close"] < bar["open"]
        has_lower_wick = wick_low > body * 0.5
        return is_bearish and has_lower_wick and volume_ok

    return False


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    bars_m1 = get_bars(data_dir, symbol, "M1")
    bars_m5 = get_bars(data_dir, symbol, "M5")

    if not bars_m1:
        print("No data found")
        return

    # ── Step 1: Build Daily Volume Profile from M5 bars ──────────────
    profile = compute_volume_profile(bars_m5, row_size=1.0) if bars_m5 else None

    if profile:
        vah = profile["vah"]
        val = profile["val"]
        poc = profile["poc"]
        log.event(
            1, "Daily Volume Profile Built", bars_m1[0]["time"], poc, "M5",
            f"VAH={vah:.2f}, VAL={val:.2f}, POC={poc:.2f}, Volume={profile['total_volume']:.0f}"
        )
    else:
        log.event(1, "Daily Volume Profile", bars_m1[0]["time"], 0, "M5",
                  "Could not build from M5. Using M1 estimate.")
        closes = [b["close"] for b in bars_m1]
        vah = max(closes)
        val = min(closes)
        poc = (vah + val) / 2

    # VWAP approximation
    vwap = sum(b["close"] * b.get("volume", 1) for b in bars_m1) / \
        max(sum(b.get("volume", 1) for b in bars_m1), 1)

    log.event(1, "VWAP Calculated", bars_m1[0]["time"], vwap, "M1",
              f"VWAP={vwap:.2f}")

    # ── State Machine ──────────────────────────────────────────────
    state = "WAIT_930_OPEN"
    absorption_index = None
    absorption_price = 0.0
    absorption_volume = 0
    trade_taken = False

    for i in range(1, len(bars_m1)):
        bar = bars_m1[i]
        ny = get_ny_time(bar["time"])

        # Skip before 9:30 AM NY
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue

        # Limit to reasonable trading hours
        if ny.hour >= 16:
            break

        if trade_taken:
            break

        prev_20 = bars_m1[max(0, i - 20):i]

        # ── Step 2 & 3: Short Setup at VAH/POC ─────────────────────
        if state == "WAIT_930_OPEN":
            # Check if price is near VAH area and we see buyer absorption
            near_vah = bar["high"] >= vah * 0.999 and bar["low"] <= vah * 1.001
            near_poc = abs(bar["close"] - poc) < (vah - val) * 0.1

            if near_vah or near_poc:
                if detect_absorption_at_wick(bar, prev_20, "bullish_absorption"):
                    absorption_index = i
                    absorption_price = bar["high"]
                    absorption_volume = bar.get("volume", 0)
                    state = "WAIT_CLOSE_BELOW_ABSORPTION"
                    log.event(
                        2, "Buyer Absorption Detected at VAH", bar["time"],
                        bar["high"], "M1",
                        f"Volume={absorption_volume}, Upper wick shows aggressive buys trapped. "
                        f"Price stalled at {bar['high']:.2f}"
                    )

        elif state == "WAIT_CLOSE_BELOW_ABSORPTION":
            # Step 3: Wait for 1-min candle to close below the absorption cluster
            # The absorption created a local support level; we need it to break
            if bar["close"] < absorption_price * 0.9995:
                log.event(
                    3, "Local Order Inversion - Short Trigger", bar["time"],
                    bar["close"], "M1",
                    f"1-min candle closed below absorption cluster at {absorption_price:.2f}. "
                    f"Support turned resistance."
                )

                sl = round(absorption_price * 1.0003, 5)
                tp = round(val, 5)

                log.trade(
                    "SHORT", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                    {"absorption_volume": absorption_volume,
                     "absorption_price": absorption_price,
                     "setup_type": "VAH_Absorption_Short"}
                )
                trade_taken = True
                log.event(5, "Trade Executed - Short", bar["time"], bar["close"], "M1",
                          f"SL={sl:.2f}, TP={tp:.2f}, R:R=1:{(bar['close']-tp)/max(sl-bar['close'],0.001):.2f}")
                break

        # ── Step 4: Long Setup at VAL ─────────────────────────────
        # Also check for long setup if price has moved below VAL
        if not trade_taken and bar["low"] <= val * 1.001:
            if detect_absorption_at_wick(bar, prev_20, "bearish_absorption"):
                absorption_index = i
                absorption_price = bar["low"]
                absorption_volume = bar.get("volume", 0)
                state = "WAIT_CLOSE_ABOVE_ABSORPTION_LONG"
                log.event(
                    2, "Seller Absorption Detected at VAL", bar["time"],
                    bar["low"], "M1",
                    f"Volume={absorption_volume}, Lower wick shows aggressive sells trapped. "
                    f"Price stalled at {bar['low']:.2f}. Discount zone - shifting to long bias."
                )

        elif state == "WAIT_CLOSE_ABOVE_ABSORPTION_LONG":
            # Step 4: Wait for bullish candle to close back above the absorbed sell orders
            if bar["close"] > absorption_price * 1.0005 and bar["close"] > bar["open"]:
                log.event(
                    3, "Seller Absorption Inversion - Long Trigger", bar["time"],
                    bar["close"], "M1",
                    f"Bullish candle closed above absorbed sell cluster at {absorption_price:.2f}. "
                    f"Resistance turned support."
                )

                sl = round(absorption_price * 0.9997, 5)
                tp = round(vwap, 5)

                log.trade(
                    "LONG", bar["close"], sl, tp, bar["time"], symbol, STRATEGY_NAME,
                    {"absorption_volume": absorption_volume,
                     "absorption_price": absorption_price,
                     "setup_type": "VAL_Absorption_Long"}
                )
                trade_taken = True
                log.event(5, "Trade Executed - Long", bar["time"], bar["close"], "M1",
                          f"SL={sl:.2f}, TP={tp:.2f}, R:R=1:{(tp-bar['close'])/max(bar['close']-sl,0.001):.2f}")
                break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
