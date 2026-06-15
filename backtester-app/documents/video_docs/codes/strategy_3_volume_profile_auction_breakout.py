"""
Strategy 3: Volume Profile Auction & Breakout Strategy
Source: Faiz SMC ("The Only Volume Profile Strategy You'll Ever Need! (FULL COURSE)")
Video: https://www.youtube.com/watch?v=dcmKOcMMT8Y

Concept:
  Uses Fixed Range Volume Profile (FRVP) to identify value areas.
  Two setups:
    A) Failed Auction: Price breaks outside VAH/VAL, then closes back inside → mean reversion to POC.
    B) Breakout: Price breaks outside and consolidates → new value acceptance → momentum continuation.

  Volume Profile settings: Row Size = 1000, Value Area Volume = 70%.
  Profile shapes: D (neutral, mean-reversion), P (bullish, break longs), b (bearish, break shorts).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional


def get_ny_time(dt: datetime) -> datetime:
    return dt


def compute_volume_profile(bars: list[dict], row_size: float = 1.0, va_volume: float = 0.70):
    """
    Compute a simple volume profile from OHLCV bars.
    Each bar's volume is distributed across price rows.
    Returns VAH, VAL, POC, and shape classification.
    """
    if not bars:
        return None

    # Build price rows
    all_prices = []
    for b in bars:
        all_prices.extend([b["high"], b["low"]])
    min_p, max_p = min(all_prices), max(all_prices)

    rows = {}
    current = min_p
    while current < max_p:
        rows[round(current, 5)] = 0
        current += row_size

    for b in bars:
        low_idx = min(rows.keys(), key=lambda x: abs(x - b["low"]))
        high_idx = min(rows.keys(), key=lambda x: abs(x - b["high"]))
        keys = sorted(rows.keys())
        start = keys.index(low_idx) if low_idx in keys else 0
        end = keys.index(high_idx) if high_idx in keys else len(keys) - 1
        vol_per_row = b.get("volume", 1) / max(end - start, 1)
        for i in range(start, end + 1):
            rows[keys[i]] += vol_per_row

    total_vol = sum(rows.values())
    sorted_rows = sorted(rows.items(), key=lambda x: x[1], reverse=True)

    # Find POC (row with max volume)
    poc_price = max(rows, key=rows.get)
    poc_vol = rows[poc_price]

    # Find Value Area (70% of volume around POC)
    va_vol_target = total_vol * va_volume
    cum_vol = 0
    va_prices = [poc_price]
    sorted_asc = sorted(rows.keys())

    poc_idx = sorted_asc.index(poc_price)
    left = poc_idx - 1
    right = poc_idx + 1
    cum_vol += rows[poc_price]

    while cum_vol < va_vol_target and (left >= 0 or right < len(sorted_asc)):
        left_vol = rows[sorted_asc[left]] if left >= 0 else 0
        right_vol = rows[sorted_asc[right]] if right < len(sorted_asc) else 0
        if left_vol >= right_vol and left >= 0:
            va_prices.append(sorted_asc[left])
            cum_vol += left_vol
            left -= 1
        elif right < len(sorted_asc):
            va_prices.append(sorted_asc[right])
            cum_vol += right_vol
            right += 1
        else:
            break

    val = min(va_prices)
    vah = max(va_prices)

    # Classify shape
    shape = "D"  # default balanced
    va_range = vah - val
    if va_range > 0:
        poc_position = (poc_price - val) / va_range
        if poc_position > 0.6:
            shape = "P"  # bullish (P-shape)
        elif poc_position < 0.4:
            shape = "b"  # bearish (b-shape)

    return {
        "vah": vah,
        "val": val,
        "poc": poc_price,
        "shape": shape,
        "total_volume": total_vol
    }


class VolumeProfileAuctionBreakout:
    def __init__(self, symbol: str = "NQ"):
        self.symbol = symbol
        self.state = "WAIT_PROFILE"
        self.profile = None
        self.last_signal = None
        self.trades = []
        self.daily_trade_count = 0
        self.last_trade_date = None

    def on_bar(self, bars: dict[str, list[dict]], current_time: datetime) -> list[dict]:
        m5_bars = bars.get("M5", [])
        m1_bars = bars.get("M1", [])

        if not m5_bars or not m1_bars:
            return []

        m5_bar = m5_bars[-1]
        ny_time = get_ny_time(current_time)

        # Reset daily trade count
        if self.last_trade_date != ny_time.date():
            self.daily_trade_count = 0
            self.last_trade_date = ny_time.date()

        # Build profile from M5 bars
        self.profile = compute_volume_profile(m5_bars[-96:] if len(m5_bars) >= 96 else m5_bars)

        if not self.profile:
            return []

        vah = self.profile["vah"]
        val = self.profile["val"]
        poc = self.profile["poc"]
        shape = self.profile["shape"]

        # Failed Auction Setup
        if self.state == "WAIT_PROFILE" and self.daily_trade_count < 2:
            # Check for close outside value area
            outside_high = m5_bar["close"] > vah
            outside_low = m5_bar["close"] < val

            if outside_high or outside_low:
                self.state = "WAIT_RETURN"
                self.breakout_high = m5_bar["high"]
                self.breakout_low = m5_bar["low"]
                self.break_direction = "high" if outside_high else "low"

        elif self.state == "WAIT_RETURN":
            # Check for close back inside value area
            if self.break_direction == "high":
                if m5_bar["close"] < vah:
                    self.state = "DONE"
                    self.daily_trade_count += 1
                    signal = {
                        "direction": "SHORT",
                        "entry": m5_bar["close"],
                        "sl": self.breakout_high + (self.breakout_high * 0.0005),
                        "tp": poc,
                        "time": current_time,
                        "symbol": self.symbol,
                        "strategy": "VolumeProfileFailedAuction"
                    }
                    self.trades.append(signal)
                    return [signal]

            elif self.break_direction == "low":
                if m5_bar["close"] > val:
                    self.state = "DONE"
                    self.daily_trade_count += 1
                    signal = {
                        "direction": "LONG",
                        "entry": m5_bar["close"],
                        "sl": self.breakout_low - (self.breakout_low * 0.0005),
                        "tp": poc,
                        "time": current_time,
                        "symbol": self.symbol,
                        "strategy": "VolumeProfileFailedAuction"
                    }
                    self.trades.append(signal)
                    return [signal]

            # If too many bars passed, reset
            self.state = "WAIT_PROFILE"

        # Breakout Setup (new value acceptance)
        if shape in ("P", "b") and self.daily_trade_count < 2:
            lookback = 10
            if len(m5_bars) >= lookback:
                recent = m5_bars[-lookback:]
                all_above_vah = all(b["low"] > vah for b in recent) and shape == "P"
                all_below_val = all(b["high"] < val for b in recent) and shape == "b"

                if all_above_vah or all_below_val:
                    consolidation_high = max(b["high"] for b in recent)
                    consolidation_low = min(b["low"] for b in recent)

                    if all_above_vah and m5_bar["close"] > consolidation_high:
                        self.daily_trade_count += 1
                        signal = {
                            "direction": "LONG",
                            "entry": m5_bar["close"],
                            "sl": consolidation_low - (consolidation_low * 0.0003),
                            "tp": m5_bar["close"] + (m5_bar["close"] - consolidation_low) * 2,
                            "time": current_time,
                            "symbol": self.symbol,
                            "strategy": "VolumeProfileBreakout"
                        }
                        self.trades.append(signal)
                        return [signal]

                    elif all_below_val and m5_bar["close"] < consolidation_low:
                        self.daily_trade_count += 1
                        signal = {
                            "direction": "SHORT",
                            "entry": m5_bar["close"],
                            "sl": consolidation_high + (consolidation_high * 0.0003),
                            "tp": m5_bar["close"] - (consolidation_high - m5_bar["close"]) * 2,
                            "time": current_time,
                            "symbol": self.symbol,
                            "strategy": "VolumeProfileBreakout"
                        }
                        self.trades.append(signal)
                        return [signal]

        return []

    def reset(self):
        self.state = "WAIT_PROFILE"
        self.profile = None
        self.last_signal = None
        self.daily_trade_count = 0


if __name__ == "__main__":
    print("Volume Profile Auction & Breakout Strategy loaded.")
    print("Feed M5 and M1 bars with 'volume' field to on_bar().")
