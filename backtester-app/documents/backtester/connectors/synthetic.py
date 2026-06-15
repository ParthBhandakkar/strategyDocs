"""
Synthetic OHLCV generator for offline backtests when MT5/local history is unavailable.
Produces reproducible pseudo-random price series with realistic bar structure.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes


class SyntheticDataClient:
    """Generates deterministic synthetic OHLCV bars for backtesting."""

    def __init__(self, seed: int = 42, base_price: float | None = None):
        self.seed = seed
        self._base_prices: dict[str, float] = {}
        if base_price is not None:
            self._default_base = base_price
        else:
            self._default_base = 1.0850

    def health_check(self) -> dict:
        return {"status": "ok", "source": "synthetic", "seed": self.seed}

    def get_symbols(self) -> list[str]:
        return [
            "EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30", "NAS100",
        ]

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        del use_cache
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        minutes = tf_to_minutes(timeframe)
        bar_delta = timedelta(minutes=minutes)
        sym_seed = int(hashlib.md5(f"{self.seed}:{symbol}".encode()).hexdigest()[:8], 16)
        rng = random.Random(sym_seed)

        base = self._base_prices.get(symbol)
        if base is None:
            base = self._default_base
            if symbol == "XAUUSD":
                base = 1950.0
            elif symbol in ("US30", "NAS100"):
                base = 38000.0 if symbol == "US30" else 18000.0
            elif symbol == "USDJPY":
                base = 150.0
            elif symbol == "GBPUSD":
                base = 1.2650
            self._base_prices[symbol] = base

        pip = 0.0001
        if symbol == "XAUUSD":
            pip = 0.1
        elif symbol in ("US30", "NAS100"):
            pip = 1.0
        elif symbol == "USDJPY":
            pip = 0.01

        bars: list[Bar] = []
        price = base
        t = start
        trend = rng.choice([-1, 1])
        trend_bars = 0

        while t <= end:
            trend_bars += 1
            if trend_bars > rng.randint(12, 48):
                trend *= -1
                trend_bars = 0

            drift = trend * pip * rng.uniform(0.2, 1.2)
            noise = rng.gauss(0, pip * rng.uniform(2, 8))
            open_p = price
            close_p = max(pip, price + drift + noise)

            wick_up = abs(rng.gauss(0, pip * 3))
            wick_dn = abs(rng.gauss(0, pip * 3))
            high_p = max(open_p, close_p) + wick_up
            low_p = min(open_p, close_p) - wick_dn
            if low_p <= 0:
                low_p = pip

            bars.append(
                Bar(
                    time=t,
                    open=round(open_p, 5),
                    high=round(high_p, 5),
                    low=round(low_p, 5),
                    close=round(close_p, 5),
                    tick_volume=rng.randint(50, 500),
                    spread=rng.randint(1, 3),
                )
            )
            price = close_p
            t += bar_delta

        return bars

    def close(self):
        pass
