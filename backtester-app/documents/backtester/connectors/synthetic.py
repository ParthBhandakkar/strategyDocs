"""
Synthetic OHLCV generator for offline/cloud backtests when local history or MT5
is unavailable.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes


class SyntheticClient:
    """Generates deterministic pseudo-market data with swings and ranges."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self._rng = random.Random(seed)

    def health_check(self) -> dict:
        return {"status": "ok", "source": "synthetic"}

    def get_symbols(self) -> list[str]:
        return ["US100", "XAUUSD", "EURUSD", "GBPUSD", "US30"]

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        del use_cache
        minutes = tf_to_minutes(timeframe)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        base_price = self._base_price(symbol)
        rng = random.Random(self.seed + hash(symbol) % 10_000 + int(timeframe))

        bars: list[Bar] = []
        current = start
        price = base_price
        trend_phase = 0.0

        while current <= end:
            trend_phase += 0.08
            drift = math.sin(trend_phase) * 0.0008 + math.sin(trend_phase * 0.31) * 0.0004
            noise = rng.uniform(-0.0012, 0.0012)
            open_price = price
            close_price = price * (1 + drift + noise)
            wick = abs(close_price - open_price) * rng.uniform(0.4, 1.8) + price * 0.0003
            high = max(open_price, close_price) + wick
            low = min(open_price, close_price) - wick
            volume = int(rng.uniform(80, 400))

            bars.append(
                Bar(
                    time=current,
                    open=round(open_price, 5),
                    high=round(high, 5),
                    low=round(low, 5),
                    close=round(close_price, 5),
                    tick_volume=volume,
                )
            )
            price = close_price
            current += timedelta(minutes=minutes)

        return bars

    @staticmethod
    def _base_price(symbol: str) -> float:
        defaults = {
            "US100": 18000.0,
            "NAS100": 18000.0,
            "NQ": 18000.0,
            "US30": 39000.0,
            "XAUUSD": 2350.0,
            "EURUSD": 1.0850,
            "GBPUSD": 1.2650,
        }
        return defaults.get(symbol.upper(), 100.0)

    def close(self) -> None:
        return


def local_history_available(path: str | Path | None) -> bool:
    if not path:
        return False
    root = Path(path)
    return root.exists() and any(root.rglob("*.csv"))
