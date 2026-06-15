"""
Strategy: Midas Model 5M Variation + 9:30 AM Model
Source: Faiz SMC ("Use This Gold Trading Strategy To Quit Your Job In 60 Days! (Midas Model)")
Video: https://www.youtube.com/watch?v=KP9RnSnr4kg

Core Concept:
  Two variants:
  1) 5M Variation (Gold, 8PM/9PM): Identify most recent 5M unswept H/L,
     wait for sweep leg that leaves FVGs, enter on FVG inversion within
     the dealing range.
  2) 9:30 AM Model: Apply same 5M logic to the NY session open
     (9:30 AM NY).
  Move to BE at closest liquidity pool. If multiple FVGs in a leg,
  wait for ALL to be inversed. 1:2 target.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "MidasModel5MVariation"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["M5", "M1"]


def find_unswept_5m_levels(m5_bars, deadline_hour, lookback=12):
    """Find most recent unswept 5M high and low before deadline_hour NY."""
    pre = [b for b in m5_bars if get_ny_time(b["time"]).hour < deadline_hour]
    if len(pre) < 3:
        return None, None, None, None

    recent = pre[-lookback:]
    high_bar = max(recent, key=lambda b: b["high"])
    low_bar = min(recent, key=lambda b: b["low"])
    return high_bar["high"], low_bar["low"], high_bar["time"], low_bar["time"]


def find_fvgs_in_move(bars, start_idx, end_idx):
    """Find all FVGs within a range of bars."""
    seg = bars[max(0, start_idx):min(len(bars), end_idx + 1)]
    return detect_fvg(seg)


def run_5m_variation(m5_bars, m1_bars, log, session_hour, session_label,
                     symbol):
    """Run the 5M variation for one session."""
    pre_high, pre_low, pre_high_time, pre_low_time = find_unswept_5m_levels(
        m5_bars, session_hour
    )
    if pre_high is None:
        return

    ref_time = pre_high_time or m5_bars[-1]["time"]
    log.event(1, f"{session_label} 5M: Unswept Levels", ref_time,
              pre_high, "M5",
              f"High={pre_high:.2f}, Low={pre_low:.2f}")

    # Find 5M bars in session
    session_m5 = [(j, b) for j, b in enumerate(m5_bars)
                  if get_ny_time(b["time"]).hour >= session_hour]

    swept = False

    for j, bar in session_m5:
        ny = get_ny_time(bar["time"])
        if ny.hour >= session_hour + 3:
            break
        if j < 1:
            continue

        if not swept:
            if bar["low"] < pre_low:
                log.event(2, f"{session_label} 5M: Low Swept (w/ FVGs)",
                          bar["time"], bar["low"], "M5")
                swept = True
                sweep_side = "low"
                sweep_idx = j
            elif bar["high"] > pre_high:
                log.event(2, f"{session_label} 5M: High Swept (w/ FVGs)",
                          bar["time"], bar["high"], "M5")
                swept = True
                sweep_side = "high"
                sweep_idx = j
            continue

        # After sweep: identify FVGs in the sweep leg
        if sweep_idx is not None:
            fvgs = find_fvgs_in_move(m5_bars, sweep_idx, j)

            if not fvgs:
                continue

            # Wait for ALL FVGs to be inversed
            all_inversed = True
            for fvg in fvgs:
                if sweep_side == "low":
                    # Bullish: FVG bottom > top after inversion
                    if bar["close"] < fvg["top"]:
                        all_inversed = False
                else:
                    # Bearish: FVG top < bottom after inversion
                    if bar["close"] > fvg["bottom"]:
                        all_inversed = False

            if not all_inversed:
                continue

            log.event(3, f"{session_label} 5M: All FVGs Inversed",
                      bar["time"], bar["close"], "M5",
                      f"FVGs in leg: {len(fvgs)}")

            if sweep_side == "low":
                sl = round(bar["low"] * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"session": session_label, "variant": "5M",
                           "swept_level": pre_low, "fvgs_in_leg": len(fvgs),
                           "management": "BE at closest pool, 1:2 TP"})
            else:
                sl = round(bar["high"] * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"session": session_label, "variant": "5M",
                           "swept_level": pre_high, "fvgs_in_leg": len(fvgs),
                           "management": "BE at closest pool, 1:2 TP"})
            break


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    m5_bars = get_bars(data_dir, symbol, "M5")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m5_bars or not m1_bars:
        print("No data found")
        return

    # ── 5M Variation: 8PM session ───────────────────────────────────
    run_5m_variation(m5_bars, m1_bars, log, 20, "8PM", symbol)

    # ── 5M Variation: 9PM session ───────────────────────────────────
    run_5m_variation(m5_bars, m1_bars, log, 21, "9PM", symbol)

    # ── 9:30 AM Model ───────────────────────────────────────────────
    pre_high, pre_low, pre_high_time, pre_low_time = find_unswept_5m_levels(
        m5_bars, 9
    )
    if pre_high is not None:
        log.event(1, "9:30 AM: Unswept Levels",
                  pre_high_time or m5_bars[-1]["time"],
                  pre_high, "M5",
                  f"High={pre_high:.2f}, Low={pre_low:.2f}")

        # Find 5M bars starting from 9:30 AM NY
        session_m5 = [
            b for b in m5_bars
            if get_ny_time(b["time"]).hour >= 9
        ]

        swept = False
        for i, bar in enumerate(session_m5):
            ny = get_ny_time(bar["time"])
            if ny.hour >= 12:
                break

            if not swept:
                if bar["low"] < pre_low:
                    log.event(2, "9:30 AM: Low Swept", bar["time"],
                              bar["low"], "M5")
                    swept = True
                    sweep_side = "low"
                elif bar["high"] > pre_high:
                    log.event(2, "9:30 AM: High Swept", bar["time"],
                              bar["high"], "M5")
                    swept = True
                    sweep_side = "high"
                continue

            # Wait for FVG inversion
            fvgs = detect_fvg(session_m5[max(0, i - 5):i + 1])
            if not fvgs:
                continue

            inversed = False
            for fvg in fvgs:
                if sweep_side == "low" and bar["close"] > fvg["top"]:
                    inversed = True
                    break
                if sweep_side == "high" and bar["close"] < fvg["bottom"]:
                    inversed = True
                    break

            if not inversed:
                continue

            log.event(3, "9:30 AM: FVG Inversion Entry",
                      bar["time"], bar["close"], "M5")

            if sweep_side == "low":
                sl = round(bar["low"] * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"session": "9:30AM", "variant": "5M",
                           "management": "BE at closest pool, 1:2 TP"})
            else:
                sl = round(bar["high"] * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"session": "9:30AM", "variant": "5M",
                           "management": "BE at closest pool, 1:2 TP"})
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
