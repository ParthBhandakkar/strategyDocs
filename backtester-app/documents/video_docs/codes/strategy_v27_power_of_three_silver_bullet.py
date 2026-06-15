"""
Strategy: The Power of 3 (AMD) Silver Bullet Strategy
Source: Faiz SMC ("This ICT Strategy Is Boring But It Made Me Profitable")
Video: https://www.youtube.com/watch?v=exkANBItgUc

Core Concept:
  10AM 4H open. M1 manipulation leg opposite bias → MSS → fib -1.0 close.
  Entry at M1 FVG/OB from -1.0 breakout leg. TP = -2.0 SD.
  Invalid if -2.0 hit before entry. Min 2:1 RR.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "PowerOfThreeSilverBullet"
SYMBOL = "NQ"
TIMEFRAMES = ["4H", "M1"]


def detect_manipulation_leg(bars: list, open_price: float) -> dict | None:
    """Detect the manipulation leg below/above open price.
    Returns dict with 'direction', 'low', 'high', 'last_lower_high' (for bullish)
    or 'last_higher_low' (for bearish)."""
    if len(bars) < 5:
        return None

    below = all(b["close"] < open_price for b in bars[-5:])
    above = all(b["close"] > open_price for b in bars[-5:])

    sw_highs = detect_swing_highs(bars)
    sw_lows = detect_swing_lows(bars)

    if below and len(sw_highs) >= 2:
        # Bullish setup (manipulate down to discount)
        lows = [b["low"] for b in bars]
        return {
            "direction": "bullish",
            "low": min(lows),
            "high": max(b["high"] for b in bars),
            "last_lower_high": sw_highs[-1]["price"] if len(sw_highs) >= 2 else sw_highs[-1]["price"],
            "manip_low": min(lows)
        }

    if above and len(sw_lows) >= 2:
        highs = [b["high"] for b in bars]
        return {
            "direction": "bearish",
            "high": max(highs),
            "low": min(b["low"] for b in bars),
            "last_higher_low": sw_lows[-1]["price"] if len(sw_lows) >= 2 else sw_lows[-1]["price"],
            "manip_high": max(highs)
        }

    return None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "4H")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not h4_bars or not m1_bars:
        print("No data found")
        return

    # ── Step 1: 10AM 4H candle open ─────────────────────────────────
    candle_open = 0.0
    candle_time = None
    for b in h4_bars:
        ny = get_ny_time(b["time"])
        if ny.hour == 10 and ny.minute == 0:
            candle_open = b["open"]
            candle_time = b["time"]
            log.event(1, "10AM 4H Candle Open", b["time"], candle_open, "4H",
                      f"Open={candle_open:.2f}")
            break

    if not candle_time:
        log.event(1, "10AM Candle Not Found", h4_bars[-1]["time"], 0, "4H")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # ── State Machine on M1 ─────────────────────────────────────────
    state = "WAIT_MANIPULATION"
    manip = None
    trade_taken = False

    m1_start = next(
        i for i, b in enumerate(m1_bars) if b["time"] >= candle_time
    )

    for i in range(m1_start + 5, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 10 or ny.hour >= 14:
            continue
        if trade_taken:
            break

        # ── Step 2-3: Accumulation → Manipulation ────────────────
        if state == "WAIT_MANIPULATION":
            seg = m1_bars[m1_start:i + 1]
            detected = detect_manipulation_leg(seg, candle_open)
            if detected:
                manip = detected
                state = "WAIT_MSS"
                log.event(2, f"Manipulation Leg ({manip['direction'].upper()})",
                          bar["time"], bar["close"], "M1",
                          f"Manip low={manip['low']:.2f}, "
                          f"last swing={manip.get('last_lower_high', manip.get('last_higher_low', 0)):.2f}")

        # ── Step 4: MSS ───────────────────────────────────────────
        if state == "WAIT_MSS" and manip:
            recent = m1_bars[max(0, i - 5):i + 1]
            mss_list = detect_mss(recent)
            valid = [s for s in mss_list if s["direction"] == manip["direction"]]
            if not valid:
                continue

            state = "WAIT_FIB_CONFIRM"
            log.event(3, f"MSS Confirmed ({manip['direction'].upper()})",
                      bar["time"], bar["close"], "M1",
                      "Market structure shifted.")

        # ── Step 5: Silver Bullet -1.0 SD confirmation ───────────
        if state == "WAIT_FIB_CONFIRM" and manip:
            # Fib from manipulation low to last swing high (bullish)
            # or manipulation high to last swing low (bearish)
            if manip["direction"] == "bullish":
                fib_low = manip["low"]
                fib_high = manip.get("last_lower_high", manip["high"])
                sd_1_0 = fib_expansion(fib_low, fib_high, 1.0)

                # Check bar close past -1.0
                if bar["close"] > sd_1_0:
                    state = "WAIT_ENTRY"
                    log.event(4, f"Silver Bullet -1.0 SD Confirmed (Bullish)",
                              bar["time"], bar["close"], "M1",
                              f"Close above -1.0 SD={sd_1_0:.2f}")
                else:
                    continue
            else:
                fib_high = manip["high"]
                fib_low = manip.get("last_higher_low", manip["low"])
                sd_1_0 = fib_expansion(fib_high, fib_low, 1.0)

                if bar["close"] < sd_1_0:
                    state = "WAIT_ENTRY"
                    log.event(4, f"Silver Bullet -1.0 SD Confirmed (Bearish)",
                              bar["time"], bar["close"], "M1",
                              f"Close below -1.0 SD={sd_1_0:.2f}")
                else:
                    continue

            # Check -2.0 invalidation
            if manip["direction"] == "bullish":
                sd_2_0 = fib_expansion(fib_low, fib_high, 2.0)
                if bar["high"] >= sd_2_0:
                    log.event(4, "Invalidated: Price hit -2.0 before entry",
                              bar["time"], bar["close"], "M1")
                    break
            else:
                sd_2_0 = fib_expansion(fib_high, fib_low, 2.0)
                if bar["low"] <= sd_2_0:
                    log.event(4, "Invalidated: Price hit -2.0 before entry",
                              bar["time"], bar["close"], "M1")
                    break

        # ── Step 6: Entry at FVG/OB from breakout leg ────────────
        if state == "WAIT_ENTRY":
            recent = m1_bars[max(0, i - 5):i + 1]
            fvgs = detect_fvg(recent)
            valid_fvgs = [f for f in fvgs if f["direction"] == manip["direction"]]

            if not valid_fvgs:
                continue

            entry_fvg = valid_fvgs[-1]
            entry_price = (entry_fvg["top"] + entry_fvg["bottom"]) / 2

            if manip["direction"] == "bullish":
                sl = round(manip["low"] * 0.9998, 5)
                tp = round(sd_2_0, 5)
                log.trade("LONG", entry_price, sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"fourh_open": candle_open,
                           "manip_low": manip["low"],
                           "manip_high": manip["high"],
                           "sd_1_0": sd_1_0, "sd_2_0": sd_2_0,
                           "entry_fvg_top": entry_fvg["top"],
                           "entry_fvg_bottom": entry_fvg["bottom"],
                           "setup_type": "Silver Bullet"})
            else:
                sl = round(manip["high"] * 1.0002, 5)
                tp = round(sd_2_0, 5)
                log.trade("SHORT", entry_price, sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"fourh_open": candle_open,
                           "manip_low": manip["low"],
                           "manip_high": manip["high"],
                           "sd_1_0": sd_1_0, "sd_2_0": sd_2_0,
                           "entry_fvg_top": entry_fvg["top"],
                           "entry_fvg_bottom": entry_fvg["bottom"],
                           "setup_type": "Silver Bullet"})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
