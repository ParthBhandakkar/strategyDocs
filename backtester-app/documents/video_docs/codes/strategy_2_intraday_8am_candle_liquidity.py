"""
Strategy 2: Intraday 8 AM Candle Liquidity Strategy
Source: Faiz SMC ("this trading strategy is stupid but it works like magic..")
Video: https://www.youtube.com/watch?v=FT3CoupoWAE

Concept:
  1. Mark the 8:00 AM NY hourly candle's high and low after it closes at 9:00 AM.
  2. Identify nearest H1 swing high above 8AM high and swing low below 8AM low.
  3. Wait for price to sweep BOTH the 8AM boundary AND the adjacent swing point.
  4. Drop to M1, wait for an MSS + candle close back inside the 8AM boundary.
  5. Enter, SL beyond sweep wick, TP at opposite 8AM boundary.
"""

from __future__ import annotations

from datetime import datetime


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


def detect_mss(bars: list[dict], lookback: int = 2) -> list[dict]:
    """Detect Market Structure Shift."""
    shifts = []
    if len(bars) < lookback + 2:
        return shifts
    recent = bars[-(lookback + 2):]
    # Bullish MSS: higher low forms after a lower low
    if recent[-1]["low"] > recent[-2]["low"] and recent[-3]["low"] > recent[-2]["low"]:
        shifts.append({"index": len(bars) - 1, "direction": "bullish"})
    # Bearish MSS: lower high forms after a higher high
    if recent[-1]["high"] < recent[-2]["high"] and recent[-3]["high"] < recent[-2]["high"]:
        shifts.append({"index": len(bars) - 1, "direction": "bearish"})
    return shifts


class EightAMCandleLiquidityStrategy:
    def __init__(self, symbol: str = "NQ"):
        self.symbol = symbol
        self.state = "WAIT_8AM"
        self.candle_8am_high = 0.0
        self.candle_8am_low = 0.0
        self.candle_8am_mid = 0.0
        self.target_swing_high = 0.0
        self.target_swing_low = 0.0
        self.sweep_direction = None
        self.sweep_extreme = 0.0
        self.trade_date = None
        self.trades = []

    def on_bar(self, bars: dict[str, list[dict]], current_time: datetime) -> list[dict]:
        h1_bars = bars.get("H1", [])
        m1_bars = bars.get("M1", [])

        if not m1_bars:
            return []

        m1_bar = m1_bars[-1]
        ny_time = get_ny_time(current_time)

        # Reset daily
        if self.trade_date != ny_time.date() and ny_time.hour == 0:
            self.reset()
            self.trade_date = ny_time.date()

        # Step 1: Capture 8AM candle at 9:00 AM
        if self.state == "WAIT_8AM" and h1_bars:
            last_h1 = h1_bars[-1]
            ny_h1_time = get_ny_time(last_h1["time"])
            if ny_h1_time.hour == 8:
                self.candle_8am_high = last_h1["high"]
                self.candle_8am_low = last_h1["low"]
                self.candle_8am_mid = (last_h1["high"] + last_h1["low"]) / 2

                # Step 2: Find adjacent swing points
                if len(h1_bars) >= 100:
                    sw_highs = detect_swing_highs(h1_bars)
                    sw_lows = detect_swing_lows(h1_bars)

                    above_highs = [s["price"] for s in sw_highs if s["price"] > self.candle_8am_high]
                    self.target_swing_high = min(above_highs) if above_highs else \
                        self.candle_8am_high + (self.candle_8am_high - self.candle_8am_low)

                    below_lows = [s["price"] for s in sw_lows if s["price"] < self.candle_8am_low]
                    self.target_swing_low = max(below_lows) if below_lows else \
                        self.candle_8am_low - (self.candle_8am_high - self.candle_8am_low)

                self.state = "WAIT_SWEEP"
                return []

        # Step 3: Wait for sweep
        if self.state == "WAIT_SWEEP":
            if m1_bar["high"] > self.target_swing_high and m1_bar["high"] > self.candle_8am_high:
                self.sweep_direction = "high"
                self.sweep_extreme = m1_bar["high"]
                self.state = "WAIT_MSS"

            elif m1_bar["low"] < self.target_swing_low and m1_bar["low"] < self.candle_8am_low:
                self.sweep_direction = "low"
                self.sweep_extreme = m1_bar["low"]
                self.state = "WAIT_MSS"

        # Step 4: Wait for MSS + close back inside boundary
        elif self.state == "WAIT_MSS":
            if self.sweep_direction == "high":
                self.sweep_extreme = max(self.sweep_extreme, m1_bar["high"])
                if m1_bar["close"] < self.candle_8am_high:
                    shifts = detect_mss(m1_bars, lookback=2)
                    bearish_mss = [s for s in shifts if s["direction"] == "bearish"]
                    if bearish_mss:
                        self.state = "DONE"
                        signal = {
                            "direction": "SHORT",
                            "entry": m1_bar["close"],
                            "sl": self.sweep_extreme + (self.sweep_extreme * 0.0001),
                            "tp": self.candle_8am_low,
                            "time": current_time,
                            "symbol": self.symbol,
                            "strategy": "EightAMCandleLiquidity"
                        }
                        self.trades.append(signal)
                        return [signal]

            elif self.sweep_direction == "low":
                self.sweep_extreme = min(self.sweep_extreme, m1_bar["low"])
                if m1_bar["close"] > self.candle_8am_low:
                    shifts = detect_mss(m1_bars, lookback=2)
                    bullish_mss = [s for s in shifts if s["direction"] == "bullish"]
                    if bullish_mss:
                        self.state = "DONE"
                        signal = {
                            "direction": "LONG",
                            "entry": m1_bar["close"],
                            "sl": self.sweep_extreme - (self.sweep_extreme * 0.0001),
                            "tp": self.candle_8am_high,
                            "time": current_time,
                            "symbol": self.symbol,
                            "strategy": "EightAMCandleLiquidity"
                        }
                        self.trades.append(signal)
                        return [signal]

        return []

    def reset(self):
        self.state = "WAIT_8AM"
        self.candle_8am_high = 0.0
        self.candle_8am_low = 0.0
        self.candle_8am_mid = 0.0
        self.target_swing_high = 0.0
        self.target_swing_low = 0.0
        self.sweep_direction = None
        self.sweep_extreme = 0.0


if __name__ == "__main__":
    print("Intraday 8 AM Candle Liquidity Strategy loaded.")
    print("Feed H1 and M1 bars to on_bar().")
