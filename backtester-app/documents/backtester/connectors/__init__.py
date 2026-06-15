"""
Data connectors — MT5 HTTP client, local history reader, and synthetic fallback.
"""

from __future__ import annotations

import os

from backtester.connectors.synthetic import SyntheticDataClient
from backtester.connectors.local_history import LocalHistoryClient

# Re-export MT5Client from legacy module body (defined below via import pattern)
from backtester.connectors import mt5_client as _mt5_mod

MT5Client = _mt5_mod.MT5Client


def get_data_client():
    """
    Return the best available data client.

    Priority:
    1. Local Exness history (LOCAL_HISTORY_PATH)
    2. MT5 HTTP server (BACKTEST_DATA_SOURCE=mt5 or MT5_SERVER_HOST set)
    3. Synthetic OHLCV (default in cloud/CI)
    """
    source = os.getenv("BACKTEST_DATA_SOURCE", "auto").lower()
    local_path = os.getenv("LOCAL_HISTORY_PATH", "")

    if source in ("local", "auto") and local_path and os.path.isdir(local_path):
        return LocalHistoryClient(history_path=local_path)

    if source == "mt5":
        return MT5Client()

    if source == "synthetic":
        seed = int(os.getenv("SYNTHETIC_SEED", "42"))
        return SyntheticDataClient(seed=seed)

    # auto: try MT5 health, else synthetic
    client = MT5Client()
    health = client.health_check()
    if health.get("status") == "ok":
        return client
    client.close()
    seed = int(os.getenv("SYNTHETIC_SEED", "42"))
    return SyntheticDataClient(seed=seed)


__all__ = [
    "MT5Client",
    "SyntheticDataClient",
    "LocalHistoryClient",
    "get_data_client",
]
