"""
Data connectors — MT5 HTTP, local Exness history, and synthetic fallback.
"""

from __future__ import annotations

import os

from .local_history import LocalHistoryClient
from .mt5_client import MT5Client
from .synthetic import SyntheticClient, local_history_available


def get_data_client(source: str | None = None):
    """
    Resolve the active data client.

    Priority when source is None:
      1. BACKTEST_DATA_SOURCE env (local | mt5 | synthetic)
      2. local if LOCAL_HISTORY_PATH exists
      3. synthetic (cloud/offline fallback)
    """
    resolved = (source or os.getenv("BACKTEST_DATA_SOURCE", "")).lower().strip()

    if resolved == "mt5":
        return MT5Client()

    if resolved == "synthetic":
        return SyntheticClient()

    local_path = os.getenv("LOCAL_HISTORY_PATH", "")
    if resolved == "local" or (not resolved and local_history_available(local_path)):
        return LocalHistoryClient(local_path)

    if resolved == "local" and not local_history_available(local_path):
        print(
            f"[get_data_client] LOCAL_HISTORY_PATH not found ({local_path!r}); "
            "falling back to synthetic data."
        )
        return SyntheticClient()

    if not resolved:
        print("[get_data_client] No local history; using synthetic data.")
        return SyntheticClient()

    raise ValueError(f"Unknown BACKTEST_DATA_SOURCE: {resolved}")


__all__ = [
    "MT5Client",
    "LocalHistoryClient",
    "SyntheticClient",
    "get_data_client",
    "local_history_available",
]
