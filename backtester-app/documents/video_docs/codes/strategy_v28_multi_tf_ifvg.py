"""
Strategy: Multi-Timeframe Highest Inversion FVG Model (iFVG)
Source: Faiz SMC ("This 'iFVG' Strategy is The Easiest Way to Become Profitable FAST")
Video: https://www.youtube.com/watch?v=KBGaDKKtUMo

Core Concept:
  HTF DOL → 9:30 AM → 5M/15M FVG toward DOL → price returns → multi-TF iFVG
  ladder (1M→5M, pick highest). Entry at candle close past iFVG boundary.
  Invalid if close past original HTF FVG boundary.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "MultiTFIFVG"
SYMBOL = "NQ"
TIMEFRAMES = ["4H", "H1", "15M", "M5", "M1"]


def aggregate_candles(m1_bars, chunk_size: int):
    """Aggregate M1 data into higher TF candles."""
    result = []
    for j in range(0, len(m1_bars), chunk_size):
        chunk = m1_bars[j:j + chunk_size]
        if not chunk:
            continue
        result.append({
            "time": chunk[0]["time"],
            "open": chunk[0]["open"],
            "high": max(b["high"] for b in chunk),
            "low": min(b["low"] for b in chunk),
            "close": chunk[-1]["close"],
        })
    return result


def find_highest_ifvg(seg, up_to=5):
    """From 1M to up_to M, find the highest TF inverted FVG."""
    best_ifvg = None
    best_tf = 0
    for m in range(1, up_to + 1):
        candles = seg if m == 1 else aggregate_candles(seg, m)
        ifvgs = detect_ifvg(candles)
        for iv in ifvgs:
            if m > best_tf:
                best_ifvg = iv
                best_tf = m
    return best_ifvg, best_tf


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "4H")
    h1_bars = get_bars(data_dir, symbol, "H1")
    m15_bars = get_bars(data_dir, symbol, "15M")
    m5_bars = get_bars(data_dir, symbol, "M5")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m1_bars or not h1_bars:
        print("No data found")
        return

    # ── Step 1: Macro DOL ───────────────────────────────────────────
    sw_highs = detect_swing_highs(h1_bars[-40:])
    sw_lows = detect_swing_lows(h1_bars[-40:])
    dol_high = sw_highs[-1]["price"] if sw_highs else None
    dol_low = sw_lows[-1]["price"] if sw_lows else None

    log.event(1, "Macro Bias / DOL", h1_bars[-1]["time"],
              h1_bars[-1]["close"], "H1",
              f"Target highs={'%.2f' % dol_high if dol_high else 'N/A'}, "
              f"Target lows={'%.2f' % dol_low if dol_low else 'N/A'}")

    # ── Step 2: 9:30 AM filter ──────────────────────────────────────
    m1_start = next(
        (i for i, b in enumerate(m1_bars)
         if get_ny_time(b["time"]).hour >= 9 and get_ny_time(b["time"]).minute >= 30),
        0
    )

    # ── State Machine ───────────────────────────────────────────────
    state = "WAIT_DISPLACEMENT"
    htf_fvg = None
    fvg_direction = None
    trend_dir = None
    sweep_extreme = 0.0
    trade_taken = False

    for i in range(m1_start + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])
        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 12:
            break
        if trade_taken:
            break

        # ── Step 3: Displacement → fresh 5M/15M FVG ─────────────
        if state == "WAIT_DISPLACEMENT" and m5_bars:
            m5_idx = next(
                (j for j, b in enumerate(m5_bars) if b["time"] >= bar["time"]),
                None
            )
            if m5_idx and m5_idx > 2:
                m5_recent = m5_bars[max(0, m5_idx - 6):m5_idx + 1]
                m5_fvgs = detect_fvg(m5_recent)

                # All detected M5 FVGs
                for f in m5_fvgs:
                    if dol_high and f["direction"] == "bullish" and f["top"] < dol_high:
                        htf_fvg = f
                        fvg_direction = "bullish"
                        break
                    elif dol_low and f["direction"] == "bearish" and f["bottom"] > dol_low:
                        htf_fvg = f
                        fvg_direction = "bearish"
                        break

            if htf_fvg:
                trend_dir = fvg_direction
                state = "WAIT_FVG_TAP"
                log.event(2, f"5M {fvg_direction.upper()} FVG toward DOL",
                          htf_fvg["time"], htf_fvg.get("avg", 0), "M5",
                          f"Top={htf_fvg['top']:.2f}, "
                          f"Bottom={htf_fvg['bottom']:.2f}")

        # ── Step 4: Price taps HTF FVG ───────────────────────────
        if state == "WAIT_FVG_TAP" and htf_fvg:
            in_fvg = htf_fvg["bottom"] <= bar["close"] <= htf_fvg["top"]
            if not in_fvg:
                continue

            state = "WAIT_ENTRY_SETUP"
            log.event(3, "Price Returned to HTF FVG", bar["time"],
                      bar["close"], "M1")

        # ── Step 4 cont: M1 sweep inside ─────────────────────────
        if state == "WAIT_ENTRY_SETUP":
            # Check invalidation: candle closed past far boundary of HTF FVG
            if htf_fvg and fvg_direction == "bullish":
                if bar["close"] < htf_fvg["bottom"]:
                    log.event(3, "Invalidated: Closed below HTF FVG", bar["time"],
                              bar["close"], "M1")
                    break
            elif htf_fvg and fvg_direction == "bearish":
                if bar["close"] > htf_fvg["top"]:
                    log.event(3, "Invalidated: Closed above HTF FVG", bar["time"],
                              bar["close"], "M1")
                    break

            recent = m1_bars[max(0, i - 8):i + 1]
            sw_h = detect_swing_highs(recent)
            sw_l = detect_swing_lows(recent)

            if trend_dir == "bullish" and sw_l and sw_l[-1]["price"] < htf_fvg["top"]:
                sweep_extreme = sw_l[-1]["price"]
                state = "WAIT_IFVG"
                log.event(3, "M1 Sweep (Bullish)", bar["time"],
                          bar["close"], "M1")
            elif trend_dir == "bearish" and sw_h and sw_h[-1]["price"] > htf_fvg["bottom"]:
                sweep_extreme = sw_h[-1]["price"]
                state = "WAIT_IFVG"
                log.event(3, "M1 Sweep (Bearish)", bar["time"],
                          bar["close"], "M1")

        # ── Step 5-6: Highest TF iFVG + entry ───────────────────
        if state == "WAIT_IFVG":
            seg = m1_bars[max(0, i - 12):i + 1]
            best_ifvg, best_tf = find_highest_ifvg(seg, 5)

            if not best_ifvg or best_ifvg["direction"] != trend_dir:
                continue

            log.event(4, f"Highest TF iFVG (M{best_tf})", bar["time"],
                      bar["close"], f"M{best_tf}",
                      f"Entry triggered at candle close past iFVG.")

            if trend_dir == "bullish":
                sl = round(min(b["low"] for b in m1_bars[max(0, i - 5):i + 1]) * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 1.5, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"dol_high": dol_high, "dol_low": dol_low,
                           "htf_fvg_top": htf_fvg["top"],
                           "htf_fvg_bottom": htf_fvg["bottom"],
                           "ifvg_tf": f"M{best_tf}",
                           "ifvg_top": best_ifvg["top"],
                           "ifvg_bottom": best_ifvg["bottom"]})
            else:
                sl = round(max(b["high"] for b in m1_bars[max(0, i - 5):i + 1]) * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 1.5, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"dol_high": dol_high, "dol_low": dol_low,
                           "htf_fvg_top": htf_fvg["top"],
                           "htf_fvg_bottom": htf_fvg["bottom"],
                           "ifvg_tf": f"M{best_tf}",
                           "ifvg_top": best_ifvg["top"],
                           "ifvg_bottom": best_ifvg["bottom"]})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
