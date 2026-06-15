"""
Strategy: The 3-Step A+ ICT Gold Strategy
Source: Faiz SMC ("The 3-Step A+ ICT Gold Strategy (that actually works)")
Video: https://www.youtube.com/watch?v=UG9lY_LF_mw

Core Concept:
  1) H1/4H clear trend (3-second rule). No clear direction → skip.
  2) Mark H1 FVG within the trend impulse leg. Wait for pullback into it.
  3) On M5: SMT divergence vs Silver + enter via CISD or MSS.
  SL behind SMT wick. TP 1:2.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "ThreeStepGold"
SYMBOL = "XAUUSD"
TIMEFRAMES = ["H1", "M5"]


def trend_is_clear(bars, min_bars=20) -> dict | None:
    """3-second rule: must clearly see HH/HL (bull) or LH/LL (bear)."""
    if len(bars) < min_bars:
        return None
    recent = bars[-min_bars:]

    highs = [b["high"] for b in recent]
    lows = [b["low"] for b in recent]

    # Check bullish: rising highs, rising lows
    rising_highs = all(highs[i] < highs[i + 1] for i in range(len(highs) - 5, len(highs) - 1))
    rising_lows = all(lows[i] < lows[i + 1] for i in range(len(lows) - 5, len(lows) - 1))
    if rising_highs and rising_lows:
        return {"direction": "bullish"}

    # Check bearish: falling highs, falling lows
    falling_highs = all(highs[i] > highs[i + 1] for i in range(len(highs) - 5, len(highs) - 1))
    falling_lows = all(lows[i] > lows[i + 1] for i in range(len(lows) - 5, len(lows) - 1))
    if falling_highs and falling_lows:
        return {"direction": "bearish"}

    return None


def find_impulse_fvgs(bars: list, trend_dir: str) -> list:
    """Find H1 FVGs within the current impulse leg in trend direction."""
    fvgs = detect_fvg(bars)
    result = []
    for f in fvgs:
        if trend_dir == "bullish" and f["direction"] == "bullish":
            result.append(f)
        elif trend_dir == "bearish" and f["direction"] == "bearish":
            result.append(f)
    return result


def check_smt_m5(gold_high: float, gold_low: float,
                 silver_high: float, silver_low: float) -> dict | None:
    """SMT divergence: look for mismatch between gold and silver on a swing."""
    # If gold made higher high but silver made lower high → bearish SMT (gold high)
    # If gold made lower low but silver made higher low → bullish SMT (gold low)
    # Simplified: compare recent swing extremes
    return None  # Placeholder - real SMT needs swing detection


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    h1_gold = get_bars(data_dir, symbol, "H1")
    m5_gold = get_bars(data_dir, symbol, "M5")

    # Silver data for SMT
    h1_silver = get_bars(data_dir, "XAGUSD", "H1")
    m5_silver = get_bars(data_dir, "XAGUSD", "M5")

    if not h1_gold or not m5_gold:
        print("No gold data found")
        return

    has_silver = bool(h1_silver and m5_silver)
    if not has_silver:
        log.event(0, "Silver Data Missing", h1_gold[-1]["time"], 0, "",
                  "SMT divergence disabled.")

    # Find most recent FVG entries
    fvgs_h1 = detect_fvg(h1_gold)

    # ── Step 1: Trend check (3-second rule) ──────────────────────────
    trend = trend_is_clear(h1_gold, 20)
    if not trend:
        log.event(1, "No Clear Trend (3-Second Rule Failed)",
                  h1_gold[-1]["time"], h1_gold[-1]["close"], "H1",
                  "Direction not obvious in 3s. Skipping.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    trend_dir = trend["direction"]
    log.event(1, f"HTF Trend: {trend_dir.upper()}", h1_gold[-1]["time"],
              h1_gold[-1]["close"], "H1",
              "Clear trend detected within 3 seconds.")

    # ── Step 2: Find FVGs within trend ───────────────────────────────
    trend_fvgs = find_impulse_fvgs(h1_gold, trend_dir)
    if not trend_fvgs:
        log.event(2, "No Trend FVGs Found", h1_gold[-1]["time"], 0, "H1",
                  "No premium/discount FVG in impulse leg. Skipping.")
        if not output:
            output = f"output_{STRATEGY_NAME}.json"
        log.to_json(output)
        return

    # Use the nearest (most recent) FVG
    target_fvg = trend_fvgs[-1]
    log.event(2, f"Target H1 FVG ({trend_dir.upper()})",
              target_fvg["time"], target_fvg.get("avg", 0), "H1",
              f"FVG range: {target_fvg['top']:.2f} - {target_fvg['bottom']:.2f}")

    # ── State Machine on M5 ─────────────────────────────────────────
    state = "WAIT_FVG_TAP"
    fvg_tap_time = None
    trade_taken = False

    for i in range(1, len(m5_gold)):
        bar = m5_gold[i]
        ny = get_ny_time(bar["time"])

        if ny.hour < 7 or ny.hour >= 16:
            continue
        if trade_taken:
            break

        fvg_top = target_fvg["top"]
        fvg_bottom = target_fvg["bottom"]

        # ── Step 3: Wait for price tap into H1 FVG ───────────────────
        if state == "WAIT_FVG_TAP":
            if trend_dir == "bullish":
                in_fvg = bar["low"] <= fvg_top and bar["high"] >= fvg_bottom
            else:
                in_fvg = bar["high"] >= fvg_bottom and bar["low"] <= fvg_top

            if in_fvg:
                state = "WAIT_SMT_CONFIRM"
                fvg_tap_time = bar["time"]
                log.event(3, "H1 FVG Tapped", bar["time"], bar["close"], "M5",
                          "Price entered the target H1 FVG zone.")

        # ── Step 3b: SMT Confirm + Entry ─────────────────────────
        if state == "WAIT_SMT_CONFIRM":
            if not has_silver:
                # Without silver, use M5 CISD/MSS directly
                recent = m5_gold[max(0, i - 10):i + 1]
                mss = detect_mss(recent)
                cisd = detect_cisd(recent)

                valid_mss = [s for s in mss if s["direction"] == trend_dir]
                valid_cisd = [s for s in cisd if s["direction"] == trend_dir]

                if valid_mss or valid_cisd:
                    entry_type = "MSS" if valid_mss else "CISD"
                    log.event(4, f"Entry Trigger: {entry_type}", bar["time"],
                              bar["close"], "M5",
                              f"M5 confirmed {trend_dir} entry without SMT.")

                    if trend_dir == "bullish":
                        sl = round(min(b["low"] for b in m5_gold[max(0, i - 5):i + 1]) * 0.9995, 2)
                        tp = round(bar["close"] + (bar["close"] - sl) * 2, 2)
                        log.trade("LONG", bar["close"], sl, tp, bar["time"],
                                  symbol, STRATEGY_NAME,
                                  {"h1_fvg_top": fvg_top, "h1_fvg_bottom": fvg_bottom,
                                   "entry_type": entry_type, "smt": False})
                    else:
                        sl = round(max(b["high"] for b in m5_gold[max(0, i - 5):i + 1]) * 1.0005, 2)
                        tp = round(bar["close"] - (sl - bar["close"]) * 2, 2)
                        log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                                  symbol, STRATEGY_NAME,
                                  {"h1_fvg_top": fvg_top, "h1_fvg_bottom": fvg_bottom,
                                   "entry_type": entry_type, "smt": False})
                    trade_taken = True
                    break

            if has_silver:
                # Find corresponding M5 silver bar
                silver_idx = next(
                    (j for j in range(len(m5_silver))
                     if m5_silver[j]["time"] >= bar["time"]),
                    None
                )
                if silver_idx is None or silver_idx < 1:
                    continue

                # Compare local swings for SMT
                g_seg = m5_gold[max(0, i - 8):i + 1]
                s_seg = m5_silver[max(0, silver_idx - 8):silver_idx + 1]

                g_high = max(b["high"] for b in g_seg)
                g_low = min(b["low"] for b in g_seg)
                s_high = max(b["high"] for b in s_seg)
                s_low = min(b["low"] for b in s_seg)

                smt = None
                if trend_dir == "bullish":
                    # Gold lower low, Silver higher low → bullish SMT
                    if g_low < g_seg[0]["low"] and s_low >= s_seg[0]["low"]:
                        smt = "bullish"
                else:
                    # Gold higher high, Silver lower high → bearish SMT
                    if g_high > g_seg[0]["high"] and s_high <= s_seg[0]["high"]:
                        smt = "bearish"

                if smt != trend_dir:
                    # SMT not matching → wait for better divergence
                    continue

                log.event(3, "SMT Divergence Confirmed", bar["time"],
                          bar["close"], "M5",
                          f"Gold→{trend_dir}, Silver→{'higher low' if trend_dir=='bullish' else 'lower high'}")

                # CISD or MSS
                recent = m5_gold[max(0, i - 10):i + 1]
                mss = detect_mss(recent)
                cisd = detect_cisd(recent)

                valid_mss = [s for s in mss if s["direction"] == trend_dir]
                valid_cisd = [s for s in cisd if s["direction"] == trend_dir]

                if not (valid_mss or valid_cisd):
                    continue

                entry_type = "MSS" if valid_mss else "CISD"
                log.event(4, f"Entry Trigger: {entry_type} + SMT", bar["time"],
                          bar["close"], "M5",
                          f"All conditions met for {trend_dir} entry.")

                if trend_dir == "bullish":
                    sl = round(g_low * 0.9995, 2)
                    tp = round(bar["close"] + (bar["close"] - sl) * 2, 2)
                    log.trade("LONG", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"h1_fvg_top": fvg_top, "h1_fvg_bottom": fvg_bottom,
                               "entry_type": entry_type, "smt": True,
                               "silver_low": g_low})
                else:
                    sl = round(g_high * 1.0005, 2)
                    tp = round(bar["close"] - (sl - bar["close"]) * 2, 2)
                    log.trade("SHORT", bar["close"], sl, tp, bar["time"],
                              symbol, STRATEGY_NAME,
                              {"h1_fvg_top": fvg_top, "h1_fvg_bottom": fvg_bottom,
                               "entry_type": entry_type, "smt": True,
                               "silver_high": g_high})
                trade_taken = True
                break

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
