"""
Strategy: Macro Volume Profile and ICT Confluence Strategy
Source: Faiz SMC ("Volume Profile + ICT = Easy Profit")
Video: https://www.youtube.com/watch?v=hIn61C0nRqY

Core Concept:
  Plot FOUR volume profiles: Previous Week, Previous Day, Overnight (18:00-09:30),
  and Developing NY Session.
  Use ONLY Previous Week, Previous Day, and Overnight levels as actionable.
  At macro level retests (M5), drop to M1 for ICT triggers: CISD, IFVG, MSS+FVG, Breaker, OTE.
  Multi-profile overlap = amplified level strength.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *

STRATEGY_NAME = "MacroVolumeProfileICT"
SYMBOL = "NQ"
TIMEFRAMES = ["M1", "M5"]


def run(data_dir: str, symbol: str = SYMBOL, output: str = ""):
    log = EventLog()

    bars_m1 = get_bars(data_dir, symbol, "M1")
    bars_m5 = get_bars(data_dir, symbol, "M5")

    if not bars_m1:
        print("No data found")
        return

    # ── Step 1: Build Overnight Profile (18:00-09:30) ──────────────
    overnight_bars = [
        b for b in bars_m5
        if get_ny_time(b["time"]).hour >= 18 or get_ny_time(b["time"]).hour < 9 or
        (get_ny_time(b["time"]).hour == 9 and get_ny_time(b["time"]).minute < 30)
    ]

    ovn_profile = compute_volume_profile(overnight_bars, row_size=1.0) if overnight_bars else None
    key_levels = {}

    if ovn_profile:
        key_levels["ovn_vah"] = ovn_profile["vah"]
        key_levels["ovn_val"] = ovn_profile["val"]
        key_levels["ovn_poc"] = ovn_profile["poc"]
        log.event(
            1, "Overnight Profile (18:00-09:30)", bars_m1[0]["time"],
            ovn_profile["poc"], "M5",
            f"VAH={ovn_profile['vah']:.2f}, VAL={ovn_profile['val']:.2f}, "
            f"POC={ovn_profile['poc']:.2f}"
        )
    else:
        log.event(1, "Overnight Profile - Not Available", bars_m1[0]["time"],
                  0, "M5", "Insufficient data.")
        return

    # Also try building Previous Day profile from last day's M5 data
    daily_bars_by_date = group_bars_by_date(bars_m5)
    dates = sorted(daily_bars_by_date.keys())
    prev_day_profile = None
    if len(dates) >= 2:
        prev_day_bars = daily_bars_by_date[dates[-2]]
        prev_day_profile = compute_volume_profile(prev_day_bars, row_size=1.0)
        if prev_day_profile:
            key_levels["pd_vah"] = prev_day_profile["vah"]
            key_levels["pd_val"] = prev_day_profile["val"]
            key_levels["pd_poc"] = prev_day_profile["poc"]
            log.event(
                1, "Previous Day Profile", bars_m1[0]["time"],
                prev_day_profile["poc"], "M5",
                f"VAH={prev_day_profile['vah']:.2f}, "
                f"VAL={prev_day_profile['val']:.2f}"
            )

    # ── State Machine ────────────────────────────────────────────────
    state = "MONITOR_M5"
    m5_failed_auction_level = 0.0
    m5_failed_direction = None
    trade_taken = False

    # Collect all key price levels for reference
    all_levels = list(key_levels.values())

    for i in range(1, len(bars_m5)):
        m5_bar = bars_m5[i]
        m5_prev = bars_m5[i - 1]
        ny = get_ny_time(m5_bar["time"])

        if ny.hour < 9 or (ny.hour == 9 and ny.minute < 30):
            continue

        if ny.hour >= 16:
            break

        if trade_taken:
            break

        # ── Step 2: Monitor M5 for Failed Auction at key levels ─────
        if state == "MONITOR_M5":
            for level_name, level_price in key_levels.items():
                if not level_price:
                    continue

                # Check for 5-min failed auction: close past level, then close back
                if m5_prev["close"] > level_price and m5_bar["close"] < level_price:
                    # Level broken up then closed back below → bearish failed auction
                    m5_failed_auction_level = level_price
                    m5_failed_direction = "short"
                    state = "DROP_TO_M1"
                    log.event(
                        2, f"M5 Failed Auction at {level_name}={level_price:.2f}",
                        m5_bar["time"], m5_bar["close"], "M5",
                        f"Price broke above then closed back below. "
                        f"Dropping to M1 for ICT trigger."
                    )
                    break

                elif m5_prev["close"] < level_price and m5_bar["close"] > level_price:
                    # Level broken down then closed back above → bullish failed auction
                    m5_failed_auction_level = level_price
                    m5_failed_direction = "long"
                    state = "DROP_TO_M1"
                    log.event(
                        2, f"M5 Failed Auction at {level_name}={level_price:.2f}",
                        m5_bar["time"], m5_bar["close"], "M5",
                        f"Price broke below then closed back above. "
                        f"Dropping to M1 for ICT trigger."
                    )
                    break

        # ── Step 3: M1 ICT Entry Triggers ────────────────────────────
        if state == "DROP_TO_M1":
            m5_timestamp = m5_bar["time"]
            m1_after = [
                b for b in bars_m1
                if b["time"] >= m5_timestamp
            ]

            for j in range(1, len(m1_after)):
                m1_bar = m1_after[j]
                recent = m1_after[max(0, j - 6):j + 1]

                # Look for ICT triggers: CISD, IFVG, MSS+FVG, Breaker
                cisd = detect_cisd(recent)
                ifvg = detect_ifvg(recent)
                mss = detect_mss(recent)
                fvgs = detect_fvg(recent)

                trigger_found = False
                trigger_type = ""

                if m5_failed_direction == "short":
                    # Need bearish trigger
                    bearish_cisd = [s for s in cisd if s["direction"] == "bearish"]
                    bearish_ifvg = [s for s in ifvg if s["direction"] == "bearish"]
                    bearish_mss = [s for s in mss if s["direction"] == "bearish"]
                    bearish_fvgs = [f for f in fvgs if f["direction"] == "bearish"]

                    if bearish_cisd:
                        trigger_found = True
                        trigger_type = "CISD"
                    elif bearish_ifvg:
                        trigger_found = True
                        trigger_type = "IFVG"
                    elif bearish_mss and bearish_fvgs:
                        trigger_found = True
                        trigger_type = "MSS+FVG"

                    if trigger_found:
                        log.event(
                            3, f"M1 {trigger_type} Bearish Trigger", m1_bar["time"],
                            m1_bar["close"], "M1",
                            f"ICT trigger at {m5_failed_auction_level:.2f} level. Entering short."
                        )

                        sl = round(m1_bar["high"] * 1.0002, 5)
                        tp = round(m1_bar["close"] - (m1_bar["high"] - m1_bar["low"]) * 2, 5)

                        log.trade(
                            "SHORT", m1_bar["close"], sl, tp, m1_bar["time"],
                            symbol, STRATEGY_NAME,
                            {"macro_level": m5_failed_auction_level,
                             "ict_trigger": trigger_type,
                             "level_source": level_name if 'level_name' in dir() else "unknown"}
                        )
                        trade_taken = True
                        break

                elif m5_failed_direction == "long":
                    bullish_cisd = [s for s in cisd if s["direction"] == "bullish"]
                    bullish_ifvg = [s for s in ifvg if s["direction"] == "bullish"]
                    bullish_mss = [s for s in mss if s["direction"] == "bullish"]
                    bullish_fvgs = [f for f in fvgs if f["direction"] == "bullish"]

                    if bullish_cisd:
                        trigger_found = True
                        trigger_type = "CISD"
                    elif bullish_ifvg:
                        trigger_found = True
                        trigger_type = "IFVG"
                    elif bullish_mss and bullish_fvgs:
                        trigger_found = True
                        trigger_type = "MSS+FVG"

                    if trigger_found:
                        log.event(
                            3, f"M1 {trigger_type} Bullish Trigger", m1_bar["time"],
                            m1_bar["close"], "M1",
                            f"ICT trigger at {m5_failed_auction_level:.2f} level. Entering long."
                        )

                        sl = round(m1_bar["low"] * 0.9998, 5)
                        tp = round(m1_bar["close"] + (m1_bar["high"] - m1_bar["low"]) * 2, 5)

                        log.trade(
                            "LONG", m1_bar["close"], sl, tp, m1_bar["time"],
                            symbol, STRATEGY_NAME,
                            {"macro_level": m5_failed_auction_level,
                             "ict_trigger": trigger_type,
                             "level_source": level_name if 'level_name' in dir() else "unknown"}
                        )
                        trade_taken = True
                        break

            if trade_taken:
                break

            # Reset if no trigger found within 50 M1 bars
            if len(m1_after) > 50:
                state = "MONITOR_M5"
                log.event(3, "No M1 Trigger Found - Back to M5", m5_bar["time"],
                          m5_bar["close"], "M5")

    if not output:
        output = f"output_{STRATEGY_NAME}.json"
    log.to_json(output)
    print(f"Done. Events: {len(log.events)}, Trades: {len(log.trades)} -> {output}")


if __name__ == "__main__":
    args = parse_args_standalone()
    run(args.get("data_dir", "."), args.get("symbol", SYMBOL), args.get("output", ""))
