"""
Deterministic synthetic OHLCV generator for offline backtests.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes
from backtester.connectors.data_client import DataClient


class SyntheticDataClient:
    """Generates reproducible OHLCV series when live/local data is unavailable."""

    DEFAULT_SYMBOLS = [
        "EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30", "NQ", "MNQ",
    ]

    def __init__(self, seed: int = 42):
        self.seed = seed
        self._cache: dict[tuple, list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        return list(self.DEFAULT_SYMBOLS)

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        key = (symbol.upper(), int(timeframe), start.isoformat(), end.isoformat())
        if use_cache and key in self._cache:
            return self._cache[key]

        bars = self._generate(symbol, timeframe, start, end)
        if use_cache:
            self._cache[key] = bars
        return bars

    def close(self) -> None:
        self._cache.clear()

    def _generate(
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
        base_price = self._base_price(symbol)
        rng = random.Random(self.seed ^ hash((symbol.upper(), int(timeframe))))

        bars: list[Bar] = []
        current = start
        price = base_price
        trend = 0.0

        while current <= end:
            ny_hour = (current - timedelta(hours=5)).hour
            session_vol = 1.0
            if 3 <= ny_hour < 12:
                session_vol = 1.4
            if 9 <= ny_hour < 16:
                session_vol = 1.8

            trend += rng.uniform(-0.02, 0.02)
            trend = max(-0.5, min(0.5, trend))

            move = rng.gauss(trend * 0.0008, 0.0006 * session_vol)
            open_price = price
            close_price = max(0.0001, open_price * (1 + move))
            wick = abs(rng.gauss(0, 0.0004 * session_vol))
            high = max(open_price, close_price) + wick
            low = min(open_price, close_price) - wick

            # Inject occasional liquidity sweeps during London pre-NY.
            if minutes <= 15 and 3 <= ny_hour < 9 and rng.random() < 0.03:
                if rng.random() < 0.5:
                    high += abs(rng.gauss(0, 0.0015))
                else:
                    low -= abs(rng.gauss(0, 0.0015))

            bars.append(
                Bar(
                    time=current,
                    open=round(open_price, 5),
                    high=round(high, 5),
                    low=round(low, 5),
                    close=round(close_price, 5),
                    tick_volume=int(200 + rng.random() * 800 * session_vol),
                    spread=1,
                )
            )
            price = close_price
            current += timedelta(minutes=minutes)

        return bars

    @staticmethod
    def _base_price(symbol: str) -> float:
        symbol = symbol.upper()
        defaults = {
            "EURUSD": 1.0850,
            "GBPUSD": 1.2650,
            "USDJPY": 150.50,
            "XAUUSD": 2350.0,
            "GOLD": 2350.0,
            "US30": 39500.0,
            "NQ": 18500.0,
            "MNQ": 18500.0,
            "ES": 5200.0,
        }
        return defaults.get(symbol, 1.1000 + (abs(hash(symbol)) % 1000) / 10000.0)
