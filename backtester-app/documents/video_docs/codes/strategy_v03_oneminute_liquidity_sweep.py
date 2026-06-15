"""
Strategy: One-Minute Liquidity Sweep Trading Strategy
Source: Faiz SMC ("Secret ICT Liquidity Sweep Trading Strategy With Insane Winrate!")
Video: https://www.youtube.com/watch?v=FAiYE-2zESk

Core Concept:
  Three-Strike Range Model:
  1) HTF orderflow bias (M5/M15) + DOL (H1/H4)
  2) Map M1 range boundaries via internal fractal pullback + MSS
  3) Wait for range boundary sweep + CISD/IFVG confirmation
  4) Invalid if opposite boundary breached before sweep
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "OneMinuteLiquiditySweep"
SYMBOL = "NQ"
TIMEFRAMES = ["M1", "M5", "M15", "H1"]


def map_bearish_range(bars: list[dict]) -> tuple:
    """
    Map bearish range from M1 bars.
    Look for: Initial push down → pullback with HH, HL, HH → MSS below HL.
    Returns (range_high, range_low) or (None, None).
    """
    if len(bars) < 15:
        return None, None

    # Find initial downleg: swing high → swing low
    sw_highs = detect_swing_highs(bars, lookback=2)
    sw_lows = detect_swing_lows(bars, lookback=2)

    if len(sw_highs) < 2 or len(sw_lows) < 2:
        return None, None

    # The most recent swing high should be the range high candidate
    # The lowest low in between is the range low
    recent_highs = sw_highs[-3:]
    recent_lows = sw_lows[-3:]

    if not recent_highs or not recent_lows:
        return None, None

    range_high_candidate = recent_highs[-1]["price"]
    range_low_candidate = min(s["price"] for s in recent_lows)

    # Validate: there should be an MSS signal breaking a higher low
    mss_signals = detect_mss(bars[-10:])
    bearish_mss = [s for s in mss_signals if s["direction"] == "bearish"]

    if bearish_mss:
        return range_high_candidate, range_low_candidate

    return None, None


def map_bullish_range(bars: list[dict]) -> tuple:
    """
    Map bullish range from M1 bars.
    Look for: Initial push up → pullback with LL, LH, LL → MSS above LH.
    Returns (range_high, range_low) or (None, None).
    """
    if len(bars) < 15:
        return None, None

    sw_highs = detect_swing_highs(bars, lookback=2)
    sw_lows = detect_swing_lows(bars, lookback=2)

    if len(sw_highs) < 2 or len(sw_lows) < 2:
        return None, None

    recent_highs = sw_highs[-3:]
    recent_lows = sw_lows[-3:]

    if not recent_highs or not recent_lows:
        return None, None

    range_low_candidate = recent_lows[-1]["price"]
    range_high_candidate = max(s["price"] for s in recent_highs)

    mss_signals = detect_mss(bars[-10:])
    bullish_mss = [s for s in mss_signals if s["direction"] == "bullish"]

    if bullish_mss:
        return range_high_candidate, range_low_candidate

    return None, None


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    bars_m1 = get_bars(data_dir, symbol, "M1")
    bars_m5 = get_bars(data_dir, symbol, "M5")
    bars_m15 = get_bars(data_dir, symbol, "M15")

    if not bars_m1:
        print("No data found")
        return

    # ── Step 1: HTF Orderflow Bias (M5/M15) ──────────────────────────
    bias = None
    dol_target = None

    if bars_m15 and len(bars_m15) >= 20:
        if is_bearish_orderflow(bars_m15[-20:]):
            bias = "bearish"
            sw_lows = detect_swing_lows(bars_m15[-40:])
            dol_target = sw_lows[-1]["price"] if sw_lows else \
                min(b["low"] for b in bars_m15[-20:])
        elif is_bullish_orderflow(bars_m15[-20:]):
            bias = "bullish"
            sw_highs = detect_swing_highs(bars_m15[-40:])
            dol_target = sw_highs[-1]["price"] if sw_highs else \
                max(b["high"] for b in bars_m15[-20:])

    if not bias and bars_m5 and len(bars_m5) >= 20:
        if is_bearish_orderflow(bars_m5[-20:]):
            bias = "bearish"
        elif is_bullish_orderflow(bars_m5[-20:]):
            bias = "bullish"

    if not bias:
        log.event(1, "Bias Check - No Clear Bias", bars_m1[-1]["time"],
                  bars_m1[-1]["close"], "M15",
                  "Orderflow not clearly bullish or bearish. Skipping.")
        return

    log.event(
        1, f"HTF Orderflow Bias: {bias.upper()}", bars_m1[0]["time"],
        bars_m1[0]["close"], "M15" if bars_m15 else "M5",
        f"DOL Target={'{:.2f}'.format(dol_target) if dol_target else 'N/A'}"
    )

    # ── State Machine ────────────────────────────────────────────────
    state = "WAIT_930"
    range_high = 0.0
    range_low = 0.0
    sweep_direction = None
    sweep_price = 0.0
    opposite_boundary_invalidated = False
    trade_taken = False

    for i in range(10, len(bars_m1)):
        bar = bars_m1[i]
        ny = get_ny_time(bar["time"])

        # Step 3: Trading window 9:30 AM - 2:00 PM
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 14:
            break

        if trade_taken:
            break

        # ── Step 4: Map M1 Range Boundaries ──────────────────────────
        if state == "WAIT_930" or state == "WAIT_RANGE_MAPPING":
            # Scan for range formation
            if bias == "bearish":
                rh, rl = map_bearish_range(bars_m1[max(0, i - 30):i])
                if rh and rl:
                    range_high = rh
                    range_low = rl
                    state = "WAIT_SWEEP"
                    log.event(
                        2, f"Bearish Range Mapped", bar["time"],
                        range_high, "M1",
                        f"Range High={range_high:.2f}, Range Low={range_low:.2f}. "
                        f"Wait for sweep of Range High."
                    )
            elif bias == "bullish":
                rh, rl = map_bullish_range(bars_m1[max(0, i - 30):i])
                if rh and rl:
                    range_high = rh
                    range_low = rl
                    state = "WAIT_SWEEP"
                    log.event(
                        2, f"Bullish Range Mapped", bar["time"],
                        range_low, "M1",
                        f"Range High={range_high:.2f}, Range Low={range_low:.2f}. "
                        f"Wait for sweep of Range Low."
                    )

        # ── Step 5: Wait for Sweep + Check Invalid Boundary Rule ────
        if state == "WAIT_SWEEP" and range_high and range_low:
            if bias == "bearish":
                # Check invalidation first: opposite boundary breached?
                if bar["low"] < range_low:
                    opposite_boundary_invalidated = True
                    log.event(
                        3, "INVALID - Opposite Boundary Breached", bar["time"],
                        bar["low"], "M1",
                        f"Price broke below Range Low {range_low:.2f} before sweeping "
                        f"Range High. Setup invalidated."
                    )
                    state = "INVALID"
                    continue

                # Sweep of Range High
                if bar["high"] > range_high:
                    sweep_direction = "bearish"
                    sweep_price = bar["high"]
                    state = "WAIT_CONFIRMATION"
                    log.event(
                        3, "Range High Swept - Three-Strike Setup", bar["time"],
                        bar["high"], "M1",
                        f"Price swept Range High={range_high:.2f}. "
                        f"Waiting for CISD/IFVG confirmation."
                    )

            elif bias == "bullish":
                # Check invalidation
                if bar["high"] > range_high:
                    opposite_boundary_invalidated = True
                    log.event(
                        3, "INVALID - Opposite Boundary Breached", bar["time"],
                        bar["high"], "M1",
                        f"Price broke above Range High {range_high:.2f} before sweeping "
                        f"Range Low. Setup invalidated."
                    )
                    state = "INVALID"
                    continue

                # Sweep of Range Low
                if bar["low"] < range_low:
                    sweep_direction = "bullish"
                    sweep_price = bar["low"]
                    state = "WAIT_CONFIRMATION"
                    log.event(
                        3, "Range Low Swept - Three-Strike Setup", bar["time"],
                        bar["low"], "M1",
                        f"Price swept Range Low={range_low:.2f}. "
                        f"Waiting for CISD/IFVG confirmation."
                    )

        # ── Step 6: CISD or IFVG Confirmation → Entry ───────────────
        if state == "WAIT_CONFIRMATION":
            recent_5 = bars_m1[max(0, i - 5):i + 1]
            cisd_signals = detect_cisd(recent_5)
            ifvg_signals = detect_ifvg(recent_5)

            confirmed = False
            confirmation_type = ""

            if sweep_direction == "bearish":
                # Price must close back inside range (below Range High)
                if bar["close"] < range_high:
                    # Check for CISD (bearish) or IFVG (bearish inversion)
                    bearish_cisd = [s for s in cisd_signals if s["direction"] == "bearish"]
                    bearish_ifvg = [s for s in ifvg_signals if s["direction"] == "bearish"]

                    if bearish_cisd:
                        confirmed = True
                        confirmation_type = "CISD"
                        log.event(
                            4, "Bearish CISD Confirmed", bar["time"],
                            bar["close"], "M1",
                            "Bearish CISD + close back inside range. Short trigger."
                        )
                    elif bearish_ifvg:
                        confirmed = True
                        confirmation_type = "IFVG"
                        log.event(
                            4, "Bearish IFVG Confirmed", bar["time"],
                            bar["close"], "M1",
                            "Bearish IFVG + close back inside range. Short trigger."
                        )

                if confirmed:
                    # Fibonacci 0.75 target level
                    fib_075 = fib_retracement(range_high, range_low, 0.75)
                    tp = fib_075 if fib_075 > range_low else range_low

                    sl = round(sweep_price * 1.0002, 5)
                    entry = bar["close"]

                    log.trade(
                        "SHORT", entry, sl, tp, bar["time"], symbol, STRATEGY_NAME,
                        {"range_high": range_high,
                         "range_low": range_low,
                         "sweep_price": sweep_price,
                         "dol_target": dol_target,
                         "confirmation": confirmation_type}
                    )
                    trade_taken = True
                    log.event(5, "Trade Executed - Short", bar["time"], entry, "M1",
                              f"Entry={entry:.2f}, SL={sl:.2f}, TP={tp:.2f}")
                    break

            elif sweep_direction == "bullish":
                # Price must close back inside range (above Range Low)
                if bar["close"] > range_low:
                    bullish_cisd = [s for s in cisd_signals if s["direction"] == "bullish"]
                    bullish_ifvg = [s for s in ifvg_signals if s["direction"] == "bullish"]

                    if bullish_cisd:
                        confirmed = True
                        confirmation_type = "CISD"
                        log.event(
                            4, "Bullish CISD Confirmed", bar["time"],
                            bar["close"], "M1",
                            "Bullish CISD + close back inside range. Long trigger."
                        )
                    elif bullish_ifvg:
                        confirmed = True
                        confirmation_type = "IFVG"
                        log.event(
                            4, "Bullish IFVG Confirmed", bar["time"],
                            bar["close"], "M1",
                            "Bullish IFVG + close back inside range. Long trigger."
                        )

                if confirmed:
                    fib_075 = fib_retracement(range_high, range_low, 0.75)
                    tp = fib_075 if fib_075 < range_high else range_high

                    sl = round(sweep_price * 0.9998, 5)
                    entry = bar["close"]

                    log.trade(
                        "LONG", entry, sl, tp, bar["time"], symbol, STRATEGY_NAME,
                        {"range_high": range_high,
                         "range_low": range_low,
                         "sweep_price": sweep_price,
                         "dol_target": dol_target,
                         "confirmation": confirmation_type}
                    )
                    trade_taken = True
                    log.event(5, "Trade Executed - Long", bar["time"], entry, "M1",
                              f"Entry={entry:.2f}, SL={sl:.2f}, TP={tp:.2f}")
                    break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
