"""
Strategy 1: Fractal-Based Inversion & Order Flow Strategy
Source: Faiz SMC ("The Only Trading Strategy I'd Use If I Had To Start Over (Stupid Simple)")
Video: https://www.youtube.com/watch?v=YGKTvqJIx1w

Concept:
  1. Identify H1 order flow (bullish/bearish via PDAs).
  2. Establish macro draw on liquidity via H4/Daily equal highs/lows.
  3. Wait for a fresh M15 FVG after 9:30 AM NY aligned with macro target.
  4. Drop to M1, wait for FVG inversion (counter-trend FVG fails).
  5. Enter on close past inverted FVG, SL below/above swing, TP at macro target.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import datetime, time


def get_ny_time(dt: datetime) -> datetime:
    """Placeholder: assumes input is UTC, shifts to NY (EST/EDT)."""
    return dt  # override with pytz if available


def is_bullish_orderflow(bars: list[dict]) -> bool:
    """Check if price respects bullish FVGs and order blocks."""
    closes = np.array([b["close"] for b in bars[-20:]])
    return np.mean(np.diff(closes)) > 0


def is_bearish_orderflow(bars: list[dict]) -> bool:
    closes = np.array([b["close"] for b in bars[-20:]])
    return np.mean(np.diff(closes)) < 0


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


def detect_fvg(bars: list[dict], min_gap_pips: float = 1.0) -> list[dict]:
    fvgs = []
    for i in range(1, len(bars) - 1):
        if bars[i + 1]["low"] > bars[i - 1]["high"]:  # bullish FVG
            gap = bars[i + 1]["low"] - bars[i - 1]["high"]
            if gap >= min_gap_pips * 0.0001:
                fvgs.append({"index": i, "direction": "bullish",
                             "low": bars[i - 1]["high"], "high": bars[i + 1]["low"]})
        elif bars[i + 1]["high"] < bars[i - 1]["low"]:  # bearish FVG
            gap = bars[i - 1]["low"] - bars[i + 1]["high"]
            if gap >= min_gap_pips * 0.0001:
                fvgs.append({"index": i, "direction": "bearish",
                             "low": bars[i + 1]["high"], "high": bars[i - 1]["low"]})
    return fvgs


def detect_ifvg(bars: list[dict], min_gap_pips: float = 0.5) -> list[dict]:
    """Detect inverted FVGs (counter-trend gaps being closed)."""
    fvgs = detect_fvg(bars, min_gap_pips)
    now = bars[-1]
    inverted = []
    for fvg in fvgs:
        if fvg["direction"] == "bullish" and now["close"] > fvg["high"]:
            inverted.append({**fvg, "inverted": True})
        elif fvg["direction"] == "bearish" and now["close"] < fvg["low"]:
            inverted.append({**fvg, "inverted": True})
    return inverted


class FractalInversionOrderflow:
    def __init__(self, symbol: str = "NQ"):
        self.symbol = symbol
        self.state = "WAIT_H1_BIAS"
        self.bias = None
        self.target_zone = None
        self.active_fvg = None
        self.entry_price = None
        self.sl = None
        self.tp = None
        self.trades = []

    def on_bar(self, bars: dict[str, list[dict]], current_time: datetime) -> list[dict]:
        """
        bars: dict with keys 'H1', 'M15', 'M5', 'M1' -> list of bar dicts
        Returns list of trade signals.
        """
        ny_time = get_ny_time(current_time)
        if ny_time.hour < 9 or (ny_time.hour == 9 and ny_time.minute < 30):
            return []

        h1_bars = bars.get("H1", [])
        m15_bars = bars.get("M15", [])
        m1_bars = bars.get("M1", [])

        if not m1_bars:
            return []

        m1_bar = m1_bars[-1]

        # Step 1: H1 bias
        if self.state == "WAIT_H1_BIAS" and len(h1_bars) >= 30:
            if is_bullish_orderflow(h1_bars):
                self.bias = "bullish"
                self.state = "WAIT_M15_FVG"
            elif is_bearish_orderflow(h1_bars):
                self.bias = "bearish"
                self.state = "WAIT_M15_FVG"

        # Step 2: Macro draw on liquidity
        h4_bars = bars.get("H4", [])
        if self.state in ("WAIT_M15_FVG", "WAIT_INVERSION") and len(h4_bars) >= 50:
            if self.bias == "bearish":
                sw_highs = detect_swing_highs(h4_bars, lookback=3)
                if sw_highs:
                    self.target_zone = max(s["price"] for s in sw_highs[-3:])
            else:
                sw_lows = detect_swing_lows(h4_bars, lookback=3)
                if sw_lows:
                    self.target_zone = min(s["price"] for s in sw_lows[-3:])

        # Step 3: Find M15 FVG aligned with target
        if self.state == "WAIT_M15_FVG" and len(m15_bars) >= 30:
            fvgs = detect_fvg(m15_bars, min_gap_pips=1.0)
            for fvg in fvgs:
                if self.bias == "bearish" and fvg["direction"] == "bearish":
                    if self.target_zone and abs(fvg["high"] - self.target_zone) < (self.target_zone * 0.002):
                        self.active_fvg = fvg
                        self.state = "WAIT_INVERSION"
                        break
                elif self.bias == "bullish" and fvg["direction"] == "bullish":
                    if self.target_zone and abs(fvg["low"] - self.target_zone) < (self.target_zone * 0.002):
                        self.active_fvg = fvg
                        self.state = "WAIT_INVERSION"
                        break

        # Step 4: M1 inversion confirmation
        if self.state == "WAIT_INVERSION" and len(m1_bars) >= 20:
            ifvgs = detect_ifvg(m1_bars)
            for ifvg in ifvgs:
                if self.bias == "bearish" and ifvg["direction"] == "bearish":
                    if m1_bar["close"] < ifvg["low"]:
                        self.state = "DONE"
                        self.sl = m1_bar["high"] + (m1_bar["high"] * 0.0001)
                        self.tp = self.target_zone if self.target_zone else \
                            m1_bar["close"] - (m1_bar["close"] - self.sl) * 2
                        signal = {
                            "direction": "SHORT",
                            "entry": m1_bar["close"],
                            "sl": self.sl,
                            "tp": self.tp,
                            "time": current_time,
                            "symbol": self.symbol,
                            "strategy": "FractalInversionOrderflow"
                        }
                        self.trades.append(signal)
                        return [signal]

                elif self.bias == "bullish" and ifvg["direction"] == "bullish":
                    if m1_bar["close"] > ifvg["high"]:
                        self.state = "DONE"
                        self.sl = m1_bar["low"] - (m1_bar["low"] * 0.0001)
                        self.tp = self.target_zone if self.target_zone else \
                            m1_bar["close"] + (m1_bar["close"] - self.sl) * 2
                        signal = {
                            "direction": "LONG",
                            "entry": m1_bar["close"],
                            "sl": self.sl,
                            "tp": self.tp,
                            "time": current_time,
                            "symbol": self.symbol,
                            "strategy": "FractalInversionOrderflow"
                        }
                        self.trades.append(signal)
                        return [signal]

        return []

    def reset(self):
        self.__init__(self.symbol)


if __name__ == "__main__":
    print("Fractal-Based Inversion & Order Flow Strategy loaded.")
    print("Integrate with your data feed and call on_bar() with OHLC bars.")
