"""Shared interface for OHLCV data providers."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backtester.core import Bar
from backtester.core.timeframes import TF


class DataClient(Protocol):
    """Minimal contract used by MultiTimeframeDataFeed and BacktestEngine."""

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        ...

    def get_symbols(self) -> list[str]:
        ...

    def close(self) -> None:
        ...
