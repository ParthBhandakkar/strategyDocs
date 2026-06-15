"""
Synthetic OHLCV data client for offline backtesting when MT5 is unavailable.
Generates deterministic price series with session-like structure.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime, timedelta, timezone

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes
from backtester.indicators.sessions import get_ny_time


_DEFAULT_PRICES = {
    "MNQ": 21000.0,
    "NQ": 21000.0,
    "ES": 5800.0,
    "EURUSD": 1.0850,
    "GBPUSD": 1.2650,
    "XAUUSD": 2350.0,
    "US30": 39500.0,
}


class SyntheticDataClient:
    """MT5-compatible client that synthesizes OHLCV bars for backtests."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self._cache: dict[str, list[Bar]] = {}

    def health_check(self) -> dict:
        return {"status": "ok", "source": "synthetic", "seed": self.seed}

    def get_symbols(self) -> list[str]:
        return list(_DEFAULT_PRICES.keys())

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        cache_key = self._cache_key(symbol, timeframe, start, end)
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        bars = self._generate_bars(symbol, timeframe, start, end)
        if use_cache:
            self._cache[cache_key] = bars
        return bars

    def close(self):
        self._cache.clear()

    def _cache_key(self, symbol: str, timeframe: TF, start: datetime, end: datetime) -> str:
        key_str = f"{self.seed}_{symbol}_{int(timeframe)}_{start.isoformat()}_{end.isoformat()}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def _generate_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        minutes = tf_to_minutes(timeframe)
        base_price = _DEFAULT_PRICES.get(symbol, 100.0)
        rng = random.Random(self.seed + hash(symbol) % 10000 + int(timeframe))

        bars: list[Bar] = []
        current = start.replace(second=0, microsecond=0)
        price = base_price
        day_anchor = 0.0
        day_high = 0.0
        day_low = 0.0
        sweep_injected = False
        current_day = None

        while current <= end:
            ny = get_ny_time(current)
            if current_day != ny.date():
                current_day = ny.date()
                day_anchor = price
                day_high = price
                day_low = price
                sweep_injected = False

            session_bias = self._session_drift(ny.hour, ny.minute, minutes)
            volatility = self._volatility(symbol, base_price, minutes)
            move = rng.gauss(session_bias, 1.0) * volatility

            # Build a bounded London range, then sweep one side before NY open.
            if 3 <= ny.hour < 7:
                move = rng.gauss(0.0, 0.35) * volatility
            elif 7 <= ny.hour < 9 and not sweep_injected:
                sweep_up = rng.random() < 0.5
                move = (2.5 if sweep_up else -2.5) * volatility
                sweep_injected = True
            elif 9 <= ny.hour < 10 and sweep_injected:
                move = (-1.2 if move > 0 else 1.2) * abs(move)

            open_price = price
            close_price = price + move
            wick = abs(rng.gauss(0, 1)) * volatility * 0.8
            high_price = max(open_price, close_price) + wick
            low_price = min(open_price, close_price) - wick

            day_high = max(day_high, high_price)
            day_low = min(day_low, low_price)

            bars.append(
                Bar(
                    time=current,
                    open=round(open_price, 5),
                    high=round(high_price, 5),
                    low=round(low_price, 5),
                    close=round(close_price, 5),
                    tick_volume=rng.randint(50, 500),
                    spread=1,
                )
            )
            price = close_price
            current += timedelta(minutes=minutes)

        return bars

    @staticmethod
    def _volatility(symbol: str, base_price: float, minutes: int) -> float:
        volatility = base_price * 0.00015 * math.sqrt(minutes)
        if symbol.startswith("XAU"):
            volatility = base_price * 0.00025 * math.sqrt(minutes)
        elif symbol in ("MNQ", "NQ", "ES", "US30"):
            volatility = base_price * 0.0002 * math.sqrt(minutes)
        return volatility

    @staticmethod
    def _session_drift(hour: int, minute: int, bar_minutes: int) -> float:
        """Bias price movement by session to create sweep-friendly structure."""
        if 3 <= hour < 9:
            return 0.15 if minute % (bar_minutes * 3) == 0 else 0.05
        if 9 <= hour < 12:
            return -0.1
        if 12 <= hour < 16:
            return 0.08
        return 0.0
