"""
Strategy: ICT Liquidity Sweep Strategy (Forex & Futures)
Source: Faiz SMC ("Easy ICT Liquidity Sweep Strategy Made Me $14,512 Today! (Full Trade Breakdown)")
Video: https://www.youtube.com/watch?v=6moA5TnQ2Ss

Core Concept:
  HTF POI → LTF entry. Forex: 1H/4H FVG as POI, 5M SMT divergence
  + FVG inversion entry. Futures (NQ/ES): 15M H/L as POI, 1M SMT
  divergence after sweep + FVG/breaker entry.
  1:2-1:2.5 RR, 30-40% partial at 1:1, BE at 1:1.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "ICTLiquiditySweep"
SYMBOL = "NQ"
TIMEFRAMES = ["H1", "M15", "M5", "M1"]


def find_htf_poi_forex(bars_h1: list):
    """Find 1H FVG as POI for Forex."""
    fvgs = detect_fvg(bars_h1)
    return fvgs


def find_htf_poi_futures(bars_m15: list):
    """Find 15M high/low as POI for Futures."""
    if len(bars_m15) < 10:
        return None, None

    recent = bars_m15[-10:]
    return max(b["high"] for b in recent), min(b["low"] for b in recent)


def check_smt_divergence(primary_bars: list, idx: int, corr_bars: list,
                         direction: str):
    """Check SMT divergence between primary and correlated asset."""
    if not corr_bars or len(corr_bars) < 10:
        return False

    p_recent = primary_bars[max(0, idx - 10):idx + 1]
    c_recent = corr_bars[-10:]

    if direction == "bullish":
        # Primary makes lower low, correlated does not
        p_low = min(b["low"] for b in p_recent)
        c_low = min(b["low"] for b in c_recent)
        return p_low < p_recent[-2]["low"] and c_low >= c_recent[-2]["low"]
    else:
        p_high = max(b["high"] for b in p_recent)
        c_high = max(b["high"] for b in c_recent)
        return p_high > p_recent[-2]["high"] and c_high <= c_recent[-2]["high"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_bars = get_bars(data_dir, symbol, "H1")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m5_bars = get_bars(data_dir, symbol, "M5")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m15_bars:
        print("No data found")
        return

    is_forex = symbol not in ["NQ", "ES", "YM", "RTY"]

    # ── Step 1: HTF POI ────────────────────────────────────────────
    if is_forex and h1_bars:
        fvgs = find_htf_poi_forex(h1_bars)
        if fvgs:
            log.event(1, "1H FVG POI (Forex)", h1_bars[-1]["time"], 0,
                      "H1", f"Count: {len(fvgs)}")
    else:
        poi_high, poi_low = find_htf_poi_futures(m15_bars)
        if poi_high is not None:
            log.event(1, "15M POI (Futures)", m15_bars[-1]["time"],
                      poi_high, "M15",
                      f"High={poi_high:.2f}, Low={poi_low:.2f}")

    # ── Step 2: LTF Entry ──────────────────────────────────────────
    if is_forex:
        # Forex: 5M TF, SMT divergence with correlated pair
        corr_symbol = "EURUSD" if symbol == "GBPUSD" else "GBPUSD"
        corr_bars = get_bars(data_dir, corr_symbol, "M5")

        for i in range(10, len(m5_bars)):
            bar = m5_bars[i]
            ny = get_ny_time(bar["time"])
            if ny.hour < 8 or ny.hour > 16:
                continue

            # Check SMT divergence
            smt_bull = check_smt_divergence(m5_bars, i, corr_bars, "bullish")
            smt_bear = check_smt_divergence(m5_bars, i, corr_bars, "bearish")

            if not smt_bull and not smt_bear:
                continue

            direction = "bullish" if smt_bull else "bearish"
            log.event(2, f"SMT Divergence ({direction.upper()})",
                      bar["time"], bar["close"], "M5",
                      f"{symbol}/{corr_symbol}")

            # Find FVG inversion
            fvgs = detect_fvg(m5_bars[max(0, i - 8):i + 1])
            if not fvgs:
                continue

            for fvg in fvgs:
                if direction == "bullish" and bar["close"] > fvg["top"]:
                    log.event(3, "5M FVG Inversion (Long)", bar["time"],
                              bar["close"], "M5")

                    sl = round(bar["low"] * 0.9998, 5)
                    tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                    log.trade("LONG", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"type": "Forex", "smt_pair": corr_symbol,
                               "management": "30-40% partial at 1:1, BE at 1:1"})
                    break
                if direction == "bearish" and bar["close"] < fvg["bottom"]:
                    log.event(3, "5M FVG Inversion (Short)", bar["time"],
                              bar["close"], "M5")

                    sl = round(bar["high"] * 1.0002, 5)
                    tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                    log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"type": "Forex", "smt_pair": corr_symbol,
                               "management": "30-40% partial at 1:1, BE at 1:1"})
                    break
            break
    else:
        # Futures: 1M TF
        corr_symbol = "ES" if symbol == "NQ" else "NQ"
        corr_bars = get_bars(data_dir, corr_symbol, "M1")

        for i in range(10, len(m1_bars)):
            bar = m1_bars[i]
            ny = get_ny_time(bar["time"])
            if ny.hour < 8 or ny.hour > 16:
                continue

            smt_bull = check_smt_divergence(m1_bars, i, corr_bars, "bullish")
            smt_bear = check_smt_divergence(m1_bars, i, corr_bars, "bearish")

            if not smt_bull and not smt_bear:
                continue

            direction = "bullish" if smt_bull else "bearish"
            log.event(2, f"SMT Divergence ({direction.upper()})",
                      bar["time"], bar["close"], "M1",
                      f"{symbol}/{corr_symbol}")

            fvgs = detect_fvg(m1_bars[max(0, i - 8):i + 1])
            if not fvgs:
                continue

            for fvg in fvgs:
                if direction == "bullish" and bar["close"] > fvg["top"]:
                    log.event(3, "1M FVG Inversion (Long)", bar["time"],
                              bar["close"], "M1")

                    sl = round(bar["low"] * 0.9998, 5)
                    tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                    log.trade("LONG", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"type": "Futures",
                               "management": "30-40% partial at 1:1, BE at 1:1"})
                    break
                if direction == "bearish" and bar["close"] < fvg["bottom"]:
                    log.event(3, "1M FVG Inversion (Short)", bar["time"],
                              bar["close"], "M1")

                    sl = round(bar["high"] * 1.0002, 5)
                    tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                    log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"type": "Futures",
                               "management": "30-40% partial at 1:1, BE at 1:1"})
                    break
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
