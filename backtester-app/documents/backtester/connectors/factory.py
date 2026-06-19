"""
Data client factory — selects MT5 remote or local CSV history based on configuration.
"""

from __future__ import annotations

import os
from typing import Protocol

from backtester.core import Bar
from backtester.core.timeframes import TF


class DataClient(Protocol):
    def health_check(self) -> dict: ...
    def get_symbols(self) -> list[str]: ...
    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start,
        end,
        use_cache: bool = True,
    ) -> list[Bar]: ...
    def close(self) -> None: ...


def get_data_client() -> DataClient:
    """
    DATA_SOURCE env:
      - local (default): read Exness CSVs from LOCAL_HISTORY_PATH
      - mt5: HTTP client to MT5_SERVER_HOST
    """
    source = os.getenv("DATA_SOURCE", "local").strip().lower()
    if source == "mt5":
        from backtester.connectors.mt5_client import MT5Client

        return MT5Client()
    from backtester.connectors.local_history import LocalHistoryClient

    return LocalHistoryClient()
