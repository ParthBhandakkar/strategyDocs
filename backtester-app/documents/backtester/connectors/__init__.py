"""
Data connectors for the backtester pipeline.
"""

from __future__ import annotations

import os
from typing import Protocol

from backtester.core import Bar
from backtester.core.timeframes import TF

from .exness_csv import ExnessCSVClient


class DataClient(Protocol):
    def get_symbols(self) -> list[str]: ...

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start,
        end,
    ) -> list[Bar]: ...


def default_data_root() -> str:
    return os.environ.get(
        "LOCAL_HISTORY_PATH",
        r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history",
    )


def get_data_client(data_root: str | None = None) -> ExnessCSVClient:
    root = data_root or default_data_root()
    return ExnessCSVClient(root)


__all__ = ["DataClient", "ExnessCSVClient", "default_data_root", "get_data_client"]
