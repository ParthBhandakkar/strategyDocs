"""
Strategy: 4H Core Trend & SMT Divergence System
Source: Faiz SMC ("Ultimate ICT Gold Trading Strategy With 73% Winrate..")
Video: https://www.youtube.com/watch?v=ugsA3FHiF0I

Core Concept:
  4H trend (3-sec rule) → 4H FVG in trend dir → 15M: price taps FVG + SMT with
  Silver → 15M CISD entry. Killzones: London 3-5AM, NY 7-11AM.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "FourHCoreTrendSMT"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["4H", "M15", "M1"]


def trend_is_clear_4h(bars, min_bars=10) -> str | None:
    """3-second rule on 4H."""
    if len(bars) < min_bars:
        return None
    r = bars[-min_bars:]
    highs = [b["high"] for b in r]
    lows = [b["low"] for b in r]
    if all(highs[i] < highs[i + 1] for i in range(len(highs) - 4, len(highs) - 1)):
        return "bullish"
    if all(highs[i] > highs[i + 1] for i in range(len(highs) - 4, len(highs) - 1)):
        return "bearish"
    return None


def in_killzone(ny_hour: int) -> bool:
    return (3 <= ny_hour <= 5) or (7 <= ny_hour <= 11)


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h4_bars = get_bars(data_dir, symbol, "4H")
    m15_bars = get_bars(data_dir, symbol, "M15")
    m1_bars = get_bars(data_dir, symbol, "M1")

    # Silver for SMT
    m15_silver = get_bars(data_dir, "XAGUSD", "M15")

    if not h4_bars or not m15_bars:
        print("No data found")
        return

    has_silver = bool(m15_silver)

    # ── Step 1: 4H trend ────────────────────────────────────────────
    trend = trend_is_clear_4h(h4_bars)
    if not trend:
        log.event(1, "No Clear 4H Trend", h4_bars[-1]["time"],
                  h4_bars[-1]["close"], "4H",
                  "3-sec rule failed. Skip.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(1, f"4H Trend: {trend.upper()}", h4_bars[-1]["time"],
              h4_bars[-1]["close"], "4H",
              "Clear trend from 3-sec rule.")

    # Find nearest 4H FVG in trend direction
    h4_fvgs = detect_fvg(h4_bars[-20:])
    trend_fvgs = [f for f in h4_fvgs if f["direction"] == trend]
    target_fvg = trend_fvgs[-1] if trend_fvgs else None

    if not target_fvg:
        log.event(2, "No 4H FVG in Trend Direction", h4_bars[-1]["time"], 0, "4H")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    log.event(2, f"Target 4H {trend.upper()} FVG",
              target_fvg["time"], target_fvg.get("avg", 0), "4H",
              f"Top={target_fvg['top']:.2f}, Bottom={target_fvg['bottom']:.2f}")

    # ── State Machine on 15M ────────────────────────────────────────
    state = "WAIT_FVG_TAP"
    trade_taken = False

    for i in range(1, len(m15_bars)):
        bar = m15_bars[i]
        ny = get_ny_time(bar["time"])

        if not in_killzone(ny.hour):
            continue
        if trade_taken:
            break

        # ── Step 2: Price enters 4H FVG ───────────────────────────
        if state == "WAIT_FVG_TAP":
            in_fvg = target_fvg["bottom"] <= bar["close"] <= target_fvg["top"]
            if not in_fvg:
                continue

            state = "WAIT_SMT_CISD"
            log.event(3, "Price Entered 4H FVG", bar["time"],
                      bar["close"], "15M")

        # ── Step 2-3: SMT + CISD entry ──────────────────────────
        if state == "WAIT_SMT_CISD":
            if has_silver:
                # Check SMT with Silver
                silver_bar = next(
                    (b for b in m15_silver if b["time"] >= bar["time"]),
                    None
                )
                if silver_bar:
                    g_seg = m15_bars[max(0, i - 6):i + 1]
                    s_seg = [b for b in m15_silver
                             if b["time"] >= m15_bars[max(0, i - 1)]["time"]
                             and b["time"] <= silver_bar["time"]]
                    if len(s_seg) >= 2:
                        g_low = min(b["low"] for b in g_seg)
                        s_low = min(b["low"] for b in s_seg[-4:])
                        g_high = max(b["high"] for b in g_seg)
                        s_high = max(b["high"] for b in s_seg[-4:])

                        smt_match = False
                        if trend == "bullish":
                            if g_low > g_seg[0]["low"] and s_low < s_seg[0]["low"]:
                                smt_match = True
                        else:
                            if g_high < g_seg[0]["high"] and s_high > s_seg[0]["high"]:
                                smt_match = True

                        if not smt_match:
                            continue

                        log.event(3, "SMT Divergence (Gold/Silver) Confirmed",
                                  bar["time"], bar["close"], "15M")

            # CISD entry
            recent = m15_bars[max(0, i - 6):i + 1]
            cisd_list = [s for s in detect_cisd(recent) if s["direction"] == trend]

            if not cisd_list:
                continue

            log.event(4, f"CISD Entry ({trend.upper()})", bar["time"],
                      bar["close"], "15M",
                      "Entry triggered within killzone.")

            if trend == "bullish":
                sl = round(min(b["low"] for b in m15_bars[max(0, i - 3):i + 1]) * 0.9998, 2)
                tp = round(bar["close"] + (bar["close"] - sl) * 2, 2)
                log.trade("LONG", bar["close"], sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"h4_trend": trend,
                           "h4_fvg_top": target_fvg["top"],
                           "h4_fvg_bottom": target_fvg["bottom"],
                           "smt": has_silver,
                           "cisd": True})
            else:
                sl = round(max(b["high"] for b in m15_bars[max(0, i - 3):i + 1]) * 1.0002, 2)
                tp = round(bar["close"] - (sl - bar["close"]) * 2, 2)
                log.trade("SHORT", bar["close"], sl, tp, bar["time"], symbol,
                          STRATEGY_NAME,
                          {"h4_trend": trend,
                           "h4_fvg_top": target_fvg["top"],
                           "h4_fvg_bottom": target_fvg["bottom"],
                           "smt": has_silver,
                           "cisd": True})
            trade_taken = True
            break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
