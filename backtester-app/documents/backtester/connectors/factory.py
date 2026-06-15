"""Factory for selecting the active OHLCV data source."""

from __future__ import annotations

import os
from pathlib import Path

from backtester.connectors.data_client import DataClient
from backtester.connectors.local_history import LocalHistoryClient
from backtester.connectors.mt5_client import MT5Client  # noqa: F401 — used below
from backtester.connectors.synthetic_data import SyntheticDataClient


def get_data_client(source: str | None = None) -> DataClient:
    """
    Resolve the data client based on BACKTEST_DATA_SOURCE.

    Priority when source is None:
      1. local  -> LocalHistoryClient if LOCAL_HISTORY_PATH exists
      2. mt5    -> MT5Client
      3. synthetic (fallback)
    """
    resolved = (source or os.getenv("BACKTEST_DATA_SOURCE", "local")).lower()

    if resolved == "local":
        history_path = os.getenv(
            "LOCAL_HISTORY_PATH",
            r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history",
        )
        if Path(history_path).exists():
            return LocalHistoryClient(history_path)
        resolved = "synthetic"

    if resolved == "mt5":
        return MT5Client()

    return SyntheticDataClient(seed=int(os.getenv("SYNTHETIC_DATA_SEED", "42")))
