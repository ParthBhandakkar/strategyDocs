"""
Strategy 4: Daily Power of Three (PO3) Strategy
Source: Faiz SMC ("I Simplified ICT PO3.. And It Actually Works!")
Video: https://www.youtube.com/watch?v=eMpWLS4mSiY

Concept:
  1. Plot the 10:00 AM NY 4-hour candle open as the anchor.
  2. Map 15-min swing highs/lows and FVGs on the left.
  3. After 10:00 AM open, look for manipulation leg sweeping a 15-min level / FVG.
  4. Confirm with SMT divergence between NQ and ES at the reversal pivot.
  5. Drop to M1 for CISD/Breaker Block confirmation → enter.
  6. TP at Fibonacci -2.0 to -2.5 standard deviation expansion levels.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def get_ny_time(dt: datetime) -> datetime:
    return dt


def detect_swing_highs(bars: list[dict], lookback: int = 3) -> list[dict]:
    highs = []
    for i in range(lookback, len(bars) - lookback):
        if all(bars[i]["high"] > bars[i - j]["high"] for j in range(1, lookback + 1)) and \
           all(bars[i]["high"] > bars[i + j]["high"] for j in range(1, lookback + 1)):
            highs.append({"index": i, "price": bars[i]["high"]})
    return highs


def detect_swing_lows(bars: list[dict], lookback: int = 3) -> list[dict]:
    lows = []
    for i in range(lookback, len(bars) - lookback):
        if all(bars[i]["low"] < bars[i - j]["low"] for j in range(1, lookback + 1)) and \
           all(bars[i]["low"] < bars[i + j]["low"] for j in range(1, lookback + 1)):
            lows.append({"index": i, "price": bars[i]["low"]})
    return lows


def detect_fvg(bars: list[dict], min_gap_pips: float = 0.5) -> list[dict]:
    fvgs = []
    for i in range(1, len(bars) - 1):
        if bars[i + 1]["low"] > bars[i - 1]["high"]:
            gap = bars[i + 1]["low"] - bars[i - 1]["high"]
            if gap >= min_gap_pips * 0.0001:
                fvgs.append({"index": i, "direction": "bullish",
                             "low": bars[i - 1]["high"], "high": bars[i + 1]["low"]})
        elif bars[i + 1]["high"] < bars[i - 1]["low"]:
            gap = bars[i - 1]["low"] - bars[i + 1]["high"]
            if gap >= min_gap_pips * 0.0001:
                fvgs.append({"index": i, "direction": "bearish",
                             "low": bars[i + 1]["high"], "high": bars[i - 1]["low"]})
    return fvgs


def detect_smt_divergence(
    primary_bars: list[dict],
    secondary_bars: list[dict],
    direction: str
) -> bool:
    """
    Simplified SMT divergence check.
    For shorts: primary (NQ) makes higher-high, secondary (ES) makes lower-high.
    For longs: primary makes lower-low, secondary makes higher-low.
    """
    if len(primary_bars) < 5 or len(secondary_bars) < 5:
        return False

    p1, p2 = primary_bars[-5], primary_bars[-1]
    s1, s2 = secondary_bars[-5], secondary_bars[-1]

    if direction == "bearish":
        return p2["high"] > p1["high"] and s2["high"] < s1["high"]
    elif direction == "bullish":
        return p2["low"] < p1["low"] and s2["low"] > s1["low"]
    return False


def cisd_detected(bars: list[dict]) -> bool:
    """Change in State of Delivery: simple clean break of recent structure."""
    if len(bars) < 3:
        return False
    return bars[-1]["close"] > bars[-2]["high"] or bars[-1]["close"] < bars[-2]["low"]


class DailyPO3Strategy:
    def __init__(self, symbol: str = "NQ", secondary_symbol: str = "ES"):
        self.symbol = symbol
        self.secondary_symbol = secondary_symbol
        self.state = "WAIT_10AM"
        self.anchor_10am_open = 0.0
        self.bias = None
        self.manipulation_high = 0.0
        self.manipulation_low = 0.0
        self.smt_confirmed = False
        self.trades = []

    def on_bar(
        self,
        bars: dict[str, list[dict]],
        multi_symbol_bars: dict[str, dict[str, list[dict]]],
        current_time: datetime
    ) -> list[dict]:
        h4_bars = bars.get("H4", [])
        m15_bars = bars.get("M15", [])
        m1_bars = bars.get("M1", [])

        if not m1_bars:
            return []

        m1_bar = m1_bars[-1]
        ny_time = get_ny_time(current_time)

        # Step 1: Get the 6AM candle bias filter
        if self.state == "WAIT_10AM" and len(h4_bars) >= 2:
            for b in h4_bars[-5:]:
                bt = get_ny_time(b["time"])
                if bt.hour == 6:
                    if b["high"] > h4_bars[-1]["high"] if len(h4_bars) > 1 else False:
                        self.bias = "bearish"  # buy-side sweep → expect sell-off
                    elif b["low"] < h4_bars[-1]["low"] if len(h4_bars) > 1 else False:
                        self.bias = "bullish"  # sell-side sweep → expect rally
                    break

        # Capture 10:00 AM open price
        if self.state == "WAIT_10AM" and h4_bars:
            last_h4 = h4_bars[-1]
            bt = get_ny_time(last_h4["time"])
            if bt.hour == 10:
                self.anchor_10am_open = last_h4["open"]
                self.state = "WAIT_MANIPULATION"

        # Step 2 & 3: Watch for manipulation leg + SMT divergence
        if self.state == "WAIT_MANIPULATION" and len(m15_bars) >= 20:
            m15_hist = m15_bars[-20:]
            sw_highs = detect_swing_highs(m15_hist, lookback=2)
            sw_lows = detect_swing_lows(m15_hist, lookback=2)
            fvgs = detect_fvg(m15_hist)

            # Check if price swept a 15-min level or FVG
            if self.bias == "bearish":
                recent_highs = [s["price"] for s in sw_highs[-3:]]
                for fvg in fvgs:
                    if fvg["direction"] == "bearish":
                        recent_highs.append(fvg["high"])
                if recent_highs and m1_bar["high"] > max(recent_highs):
                    self.manipulation_high = m1_bar["high"]
                    # Check SMT divergence with secondary symbol
                    sec_bars = multi_symbol_bars.get(self.secondary_symbol, {}).get("M15", [])
                    if sec_bars and detect_smt_divergence(m15_hist, sec_bars, "bearish"):
                        self.smt_confirmed = True
                        self.state = "WAIT_CISD"

            elif self.bias == "bullish":
                recent_lows = [s["price"] for s in sw_lows[-3:]]
                for fvg in fvgs:
                    if fvg["direction"] == "bullish":
                        recent_lows.append(fvg["low"])
                if recent_lows and m1_bar["low"] < min(recent_lows):
                    self.manipulation_low = m1_bar["low"]
                    sec_bars = multi_symbol_bars.get(self.secondary_symbol, {}).get("M15", [])
                    if sec_bars and detect_smt_divergence(m15_hist, sec_bars, "bullish"):
                        self.smt_confirmed = True
                        self.state = "WAIT_CISD"

        # Step 4: M1 CISD / Breaker Block entry
        if self.state == "WAIT_CISD" and cisd_detected(m1_bars[-5:]):
            self.state = "DONE"

            # Calculate Fibonacci expansion targets
            if self.bias == "bearish":
                start = self.manipulation_high
                end = min(b["low"] for b in m1_bars[-10:])
                range_move = start - end
                fib_2 = end - (range_move * 2.0)
                fib_25 = end - (range_move * 2.5)

                signal = {
                    "direction": "SHORT",
                    "entry": m1_bar["close"],
                    "sl": self.manipulation_high + (self.manipulation_high * 0.0001),
                    "tp": fib_2,
                    "fib_targets": {"-2.0": fib_2, "-2.5": fib_25},
                    "time": current_time,
                    "symbol": self.symbol,
                    "strategy": "DailyPO3"
                }
            else:
                start = self.manipulation_low
                end = max(b["high"] for b in m1_bars[-10:])
                range_move = end - start
                fib_2 = end + (range_move * 2.0)
                fib_25 = end + (range_move * 2.5)

                signal = {
                    "direction": "LONG",
                    "entry": m1_bar["close"],
                    "sl": self.manipulation_low - (self.manipulation_low * 0.0001),
                    "tp": fib_2,
                    "fib_targets": {"2.0": fib_2, "2.5": fib_25},
                    "time": current_time,
                    "symbol": self.symbol,
                    "strategy": "DailyPO3"
                }

            self.trades.append(signal)
            return [signal]

        return []

    def reset(self):
        self.state = "WAIT_10AM"
        self.anchor_10am_open = 0.0
        self.bias = None
        self.manipulation_high = 0.0
        self.manipulation_low = 0.0
        self.smt_confirmed = False


if __name__ == "__main__":
    print("Daily Power of Three (PO3) Strategy loaded.")
    print("Provide H4, M15, M1 bars + multi_symbol_bars for SMT divergence.")
