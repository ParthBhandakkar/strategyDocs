"""
Factory for selecting the backtest data source.
Local Exness history is the default for automation and CLI runs.
"""

from __future__ import annotations

import os

from backtester.connectors import MT5Client
from backtester.connectors.local_history_client import DEFAULT_HISTORY_PATH, LocalHistoryClient
from backtester.connectors.synthetic_client import SyntheticDataClient


def get_data_client(
    source: str | None = None,
    *,
    history_root: str | None = None,
    synthetic_seed: int = 42,
) -> LocalHistoryClient | MT5Client | SyntheticDataClient:
    """
    Resolve the data client used by backtests.

    Priority when source is None:
      1. LOCAL_HISTORY_PATH (or default UltimateTradeBot Exness history folder)
      2. MT5 HTTP server
      3. Synthetic data (last resort)
    """
    chosen = (source or os.getenv("BACKTEST_DATA_SOURCE", "local")).lower()

    if chosen == "local":
        return LocalHistoryClient(history_root=history_root)
    if chosen == "mt5":
        return MT5Client()
    if chosen == "synthetic":
        return SyntheticDataClient(seed=synthetic_seed)

    raise ValueError(f"Unknown data source: {source}")


def default_history_path() -> str:
    return os.getenv("LOCAL_HISTORY_PATH", DEFAULT_HISTORY_PATH)
