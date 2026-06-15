"""
Strategy 5: Gold Scalping Failed Auction Strategy
Source: Faiz SMC ("ICT Not Working? Use This Gold Trading Strategy Instead..")
Video: https://www.youtube.com/watch?v=HyJuZNo_ikM

Concept:
  Gold-specific (XAU/USD) volume profile strategy using London session (3:00-7:00 AM NY).
  1. Build FRVP from 3:00 AM to 7:00 AM NY on 5-minute chart.
  2. Mark VAH, VAL, POC from the London session profile.
  3. Post-7:00 AM, watch for price to break outside VAH/VAL.
  4. Wait for a 5-min close back inside value (Failed Auction).
  5. Enter toward POC / VAH / VAL.
  Max 2 trades/day, one per direction.
"""

from __future__ import annotations

from datetime import datetime


def get_ny_time(dt: datetime) -> datetime:
    return dt


def compute_volume_profile(bars: list[dict], row_size: float = 1.0, va_volume: float = 0.70):
    if not bars:
        return None

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
    poc_price = max(rows, key=rows.get)

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

    return {
        "vah": max(va_prices),
        "val": min(va_prices),
        "poc": poc_price,
        "total_volume": total_vol
    }


class GoldScalpingFailedAuction:
    def __init__(self, symbol: str = "XAUUSD"):
        self.symbol = symbol
        self.state = "WAIT_LONDON_PROFILE"
        self.profile = None
        self.vah = 0.0
        self.val = 0.0
        self.poc = 0.0
        self.profile_built = False
        self.trades = []
        self.daily_long_trades = 0
        self.daily_short_trades = 0
        self.last_trade_date = None
        self.break_direction = None
        self.breakout_price = 0.0

    def _get_london_session_bars(self, bars: list[dict]) -> list[dict]:
        """Filter 5-min bars to London session (3:00-7:00 AM NY)."""
        session_bars = []
        for b in bars:
            bt = get_ny_time(b["time"])
            if 3 <= bt.hour < 7:
                session_bars.append(b)
        return session_bars

    def on_bar(self, bars: dict[str, list[dict]], current_time: datetime) -> list[dict]:
        m5_bars = bars.get("M5", [])

        if not m5_bars:
            return []

        m5_bar = m5_bars[-1]
        ny_time = get_ny_time(current_time)

        # Reset daily counters
        if self.last_trade_date != ny_time.date():
            self.daily_long_trades = 0
            self.daily_short_trades = 0
            self.last_trade_date = ny_time.date()
            self.state = "WAIT_LONDON_PROFILE"

        # Step 1 & 2: Build London session profile after 7:00 AM
        if self.state == "WAIT_LONDON_PROFILE" and ny_time.hour >= 7:
            london_bars = self._get_london_session_bars(m5_bars)
            if len(london_bars) >= 10:
                self.profile = compute_volume_profile(london_bars, row_size=0.10)
                if self.profile:
                    self.vah = self.profile["vah"]
                    self.val = self.profile["val"]
                    self.poc = self.profile["poc"]
                    self.profile_built = True
                    self.state = "WAIT_BREAK"
                    print(f"London Profile built: VAH={self.vah:.2f}, VAL={self.val:.2f}, POC={self.poc:.2f}")

        if not self.profile_built:
            return []

        # Step 3: Monitor for break outside value area
        if self.state == "WAIT_BREAK":
            if m5_bar["close"] > self.vah:
                self.break_direction = "high"
                self.breakout_price = m5_bar["high"]
                self.state = "WAIT_FAILED_AUCTION"
            elif m5_bar["close"] < self.val:
                self.break_direction = "low"
                self.breakout_price = m5_bar["low"]
                self.state = "WAIT_FAILED_AUCTION"

        # Step 4: Failed Auction - close back inside value
        elif self.state == "WAIT_FAILED_AUCTION":
            can_trade = False
            if self.break_direction == "high" and self.daily_short_trades < 1:
                if m5_bar["close"] < self.vah:
                    can_trade = True
                    trade_dir = "SHORT"
                    self.daily_short_trades += 1
                    sl = self.breakout_price + (self.breakout_price * 0.0003)
                    tp1 = self.poc
                    tp2 = self.val

            elif self.break_direction == "low" and self.daily_long_trades < 1:
                if m5_bar["close"] > self.val:
                    can_trade = True
                    trade_dir = "LONG"
                    self.daily_long_trades += 1
                    sl = self.breakout_price - (self.breakout_price * 0.0003)
                    tp1 = self.poc
                    tp2 = self.vah

            if can_trade:
                self.state = "DONE"
                signal = {
                    "direction": trade_dir,
                    "entry": m5_bar["close"],
                    "sl": sl,
                    "tp": tp1,
                    "tp2": tp2,
                    "poc": self.poc,
                    "time": current_time,
                    "symbol": self.symbol,
                    "strategy": "GoldScalpingFailedAuction"
                }
                self.trades.append(signal)
                return [signal]

            # If price doesn't return soon, reset
            self.state = "WAIT_BREAK"

        return []

    def reset(self):
        self.state = "WAIT_LONDON_PROFILE"
        self.profile = None
        self.profile_built = False
        self.break_direction = None


if __name__ == "__main__":
    print("Gold Scalping Failed Auction Strategy loaded.")
    print("Feed M5 bars with 'volume' and 'time' fields to on_bar().")
