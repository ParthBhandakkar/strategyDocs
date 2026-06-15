"""
Strategy: The Only ICT Trading Strategy I'll Be Using In 2026 (80% Winrate)
Source: Faiz SMC ("The Only ICT Trading Strategy I'll Be Using In 2026! (80% Winrate)")
Video: https://www.youtube.com/watch?v=CLDEIsNpVRc

Core Concept:
  1) Map DOL (Asia/London H/L, PDH/PDL, equal H/L).
  2) 9:30-11:30 NY trade window. 5M/15M FVG toward DOL.
  3) Price returns into FVG → M1 sweep of local swing H/L.
  4) M1 IFVG with strong displacement → enter. TP 1:2 or DOL.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "OnlyICT2026"
SYMBOL = "NQ"
TIMEFRAMES = ["D1", "H1", "15M", "5M", "M1"]


def map_dol(h1_bars, d1_bars):
    """Map Draw on Liquidity from higher timeframes."""
    dol = {}

    if d1_bars and len(d1_bars) >= 2:
        prev = d1_bars[-2]
        dol["pdh"] = prev["high"]
        dol["pdl"] = prev["low"]
        dol["pdc"] = prev["close"]

    # Session highs/lows from H1
    asia_highs = [b["high"] for b in h1_bars
                  if 0 <= get_ny_time(b["time"]).hour < 8]
    asia_lows = [b["low"] for b in h1_bars
                 if 0 <= get_ny_time(b["time"]).hour < 8]
    if asia_highs:
        dol["asia_high"] = max(asia_highs)
        dol["asia_low"] = min(asia_lows)

    london_highs = [b["high"] for b in h1_bars
                    if 3 <= get_ny_time(b["time"]).hour < 8]
    london_lows = [b["low"] for b in h1_bars
                   if 3 <= get_ny_time(b["time"]).hour < 8]
    if london_highs:
        dol["london_high"] = max(london_highs)
        dol["london_low"] = min(london_lows)

    return dol


def find_m1_swing_inside(recent_m1, fvg_top, fvg_bottom):
    """Find M1 swing high/low within FVG zone."""
    inside = [b for b in recent_m1 if fvg_bottom <= b["close"] <= fvg_top]
    if not inside:
        return None
    sw_h = detect_swing_highs(inside)
    sw_l = detect_swing_lows(inside)
    return {"highs": sw_h[-1]["price"] if sw_h else None,
            "lows": sw_l[-1]["price"] if sw_l else None}


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    d1_bars = get_bars(data_dir, symbol, "D1")
    h1_bars = get_bars(data_dir, symbol, "H1")
    m15_bars = get_bars(data_dir, symbol, "15M")
    m5_bars = get_bars(data_dir, symbol, "5M")
    m1_bars = get_bars(data_dir, symbol, "M1")

    if not m1_bars or not h1_bars:
        print("No data found")
        return

    # ── Step 1: Map DOL ─────────────────────────────────────────────
    dol = map_dol(h1_bars or [], d1_bars or [])
    log.event(1, "Draw on Liquidity (DOL) Mapped",
              h1_bars[-1]["time"] if h1_bars else "",
              dol.get("pdh", 0), "HTF",
              f"PDH={dol.get('pdh'):.2f}, PDL={dol.get('pdl'):.2f}, "
              f"Asia H={dol.get('asia_high'):.2f}, "
              f"London H={dol.get('london_high'):.2f}" if dol.get("london_high") else "")

    # ── Trade window: 9:30-11:30 NY ─────────────────────────────────
    trade_start_idx = next(
        (i for i, b in enumerate(m1_bars)
         if (get_ny_time(b["time"]).hour == 9 and get_ny_time(b["time"]).minute >= 30)),
        0
    )

    # ── State Machine ───────────────────────────────────────────────
    state = "WAIT_HTF_FVG"
    htf_fvg = None
    fvg_direction = None
    sweep_dir = None
    sweep_extreme = 0.0
    trade_taken = False

    for i in range(trade_start_idx + 1, len(m1_bars)):
        bar = m1_bars[i]
        ny = get_ny_time(bar["time"])

        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue
        if ny.hour >= 11 or (ny.hour == 11 and ny.minute > 30):
            break
        if trade_taken:
            break

        # ── Step 3: Find 5M/15M FVG pointing toward DOL ──────────
        if state == "WAIT_HTF_FVG" and m5_bars:
            # Find M5 FVG recently formed
            m5_idx = next(
                (j for j, b in enumerate(m5_bars) if b["time"] >= bar["time"]),
                None
            )
            if m5_idx and m5_idx > 1:
                m5_recent = m5_bars[max(0, m5_idx - 5):m5_idx + 1]
                m5_fvgs = detect_fvg(m5_recent)
                for f in m5_fvgs:
                    # FVG pointing toward DOL
                    if f["direction"] == "bearish" and dol.get("pdl") and f["bottom"] > dol["pdl"]:
                        htf_fvg = f
                        fvg_direction = "bearish"
                        break
                    elif f["direction"] == "bullish" and dol.get("pdh") and f["top"] < dol["pdh"]:
                        htf_fvg = f
                        fvg_direction = "bullish"
                        break

            if htf_fvg:
                state = "WAIT_FVG_TAP"
                log.event(2, f"5M {fvg_direction.upper()} FVG toward DOL",
                          htf_fvg["time"], htf_fvg.get("avg", 0), "5M",
                          f"Top={htf_fvg['top']:.2f}, "
                          f"Bottom={htf_fvg['bottom']:.2f}")

        # ── Step 4: Price taps into HTF FVG ──────────────────────
        if state == "WAIT_FVG_TAP" and htf_fvg:
            in_fvg = (htf_fvg["bottom"] <= bar["high"] and
                      bar["low"] <= htf_fvg["top"])
            if not in_fvg:
                continue

            state = "WAIT_M1_SWEEP"
            log.event(3, "Price Tapped HTF FVG", bar["time"],
                      bar["close"], "M1")

        # ── Step 4 cont: M1 sweep of local swing ─────────────────
        if state == "WAIT_M1_SWEEP":
            recent_m1 = m1_bars[max(0, i - 8):i + 1]
            sw = detect_swing_highs(recent_m1)
            sl = detect_swing_lows(recent_m1)

            sell_swept = sw and htf_fvg and sw[-1]["price"] > htf_fvg["bottom"]
            buy_swept = sl and htf_fvg and sl[-1]["price"] < htf_fvg["top"]

            if sell_swept and fvg_direction == "bearish":
                sweep_dir = "bearish"
                sweep_extreme = sw[-1]["price"]
                state = "WAIT_IFVG"
                log.event(3, "M1 Sweep Inside FVG (Short)", bar["time"],
                          bar["close"], "M1",
                          f"Swept swing high @ {sweep_extreme:.2f}")

            elif buy_swept and fvg_direction == "bullish":
                sweep_dir = "bullish"
                sweep_extreme = sl[-1]["price"]
                state = "WAIT_IFVG"
                log.event(3, "M1 Sweep Inside FVG (Long)", bar["time"],
                          bar["close"], "M1",
                          f"Swept swing low @ {sweep_extreme:.2f}")

        # ── Step 5: IFVG entry ───────────────────────────────────
        if state == "WAIT_IFVG":
            recent = m1_bars[max(0, i - 8):i + 1]
            ifvgs = detect_ifvg(recent)
            valid_ifvg = [f for f in ifvgs if f["direction"] == sweep_dir]

            # Also check displacement (large candle body)
            if not valid_ifvg:
                continue

            body = abs(bar["close"] - bar["open"])
            avg_body = sum(abs(b["close"] - b["open"]) for b in recent) / len(recent)
            if body < avg_body * 1.5:
                continue  # weak displacement

            log.event(4, f"IFVG + Strong Displacement ({sweep_dir.upper()})",
                      bar["time"], bar["close"], "M1",
                      f"Entry triggered.")

            if sweep_dir == "bearish":
                sl = round(sweep_extreme * 1.0002, 5)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 5)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"dol_pdh": dol.get("pdh"),
                           "dol_pdl": dol.get("pdl"),
                           "htf_fvg_top": htf_fvg["top"],
                           "htf_fvg_bottom": htf_fvg["bottom"],
                           "fvg_direction": fvg_direction,
                           "sweep_extreme": sweep_extreme,
                           "ifvg": True, "displacement": round(body, 2)})
            else:
                sl = round(sweep_extreme * 0.9998, 5)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 5)
                log.trade("LONG", bar["close"], sl, tp, bar["time"],
                          symbol, STRATEGY_NAME,
                          {"dol_pdh": dol.get("pdh"),
                           "dol_pdl": dol.get("pdl"),
                           "htf_fvg_top": htf_fvg["top"],
                           "htf_fvg_bottom": htf_fvg["bottom"],
                           "fvg_direction": fvg_direction,
                           "sweep_extreme": sweep_extreme,
                           "ifvg": True, "displacement": round(body, 2)})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
