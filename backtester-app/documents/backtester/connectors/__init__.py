"""
MT5 HTTP Client — connects to the MT5 server running on Windows via NGROK.
Provides methods to fetch historical OHLCV data with local disk caching.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes


class MT5Client:
    """HTTP client for the remote MT5 data server exposed via NGROK."""

    def __init__(self, base_url: str | None = None, cache_dir: str | None = None, timeout: int = 30):
        self.base_url = (base_url or os.getenv("MT5_SERVER_HOST", "http://localhost:8005")).rstrip("/")
        self.timeout = timeout
        self.cache_dir = Path(cache_dir or os.path.join(os.path.dirname(__file__), "..", ".cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(
            timeout=self.timeout,
            headers={"ngrok-skip-browser-warning": "true"},
        )

    def health_check(self) -> dict:
        """Check if the MT5 server is healthy."""
        try:
            resp = self._client.get(f"{self.base_url}/health")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_symbols(self) -> list[str]:
        """Get available symbols from the MT5 server."""
        try:
            resp = self._client.get(f"{self.base_url}/symbols")
            resp.raise_for_status()
            return resp.json().get("symbols", [])
        except Exception as e:
            print(f"[MT5Client] Error fetching symbols: {e}")
            return self._default_symbols()

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        """
        Fetch OHLCV bars from the MT5 server.
        Results are cached locally to avoid redundant network calls.
        """
        cache_key = self._cache_key(symbol, timeframe, start, end)
        if use_cache:
            cached = self._load_cache(cache_key)
            if cached is not None:
                return cached

        bars = self._fetch_bars(symbol, timeframe, start, end)
        if bars and use_cache:
            self._save_cache(cache_key, bars)
        return bars

    def _fetch_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        max_retries: int = 3,
    ) -> list[Bar]:
        """Fetch bars from MT5 server with retry logic."""
        start_iso = start.isoformat() if start.tzinfo else start.replace(tzinfo=timezone.utc).isoformat()
        end_iso = end.isoformat() if end.tzinfo else end.replace(tzinfo=timezone.utc).isoformat()

        payload = {
            "symbol": symbol,
            "timeframe": int(timeframe),
            "start": start_iso,
            "end": end_iso,
        }

        for attempt in range(max_retries):
            try:
                resp = self._client.post(f"{self.base_url}/bars", json=payload)
                resp.raise_for_status()
                data = resp.json()
                raw_bars = data.get("bars", [])
                return self._parse_bars(raw_bars)
            except Exception as e:
                wait = 2 ** attempt
                print(f"[MT5Client] Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)

        print(f"[MT5Client] All {max_retries} attempts failed for {symbol} {timeframe}")
        return []

    def _parse_bars(self, raw_bars: list[dict]) -> list[Bar]:
        """Convert raw JSON bar dicts to Bar dataclasses."""
        bars = []
        for b in raw_bars:
            try:
                t = b.get("time", "")
                if isinstance(t, str):
                    t = t.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(t)
                elif isinstance(t, (int, float)):
                    dt = datetime.fromtimestamp(t, tz=timezone.utc)
                else:
                    continue

                bars.append(Bar(
                    time=dt,
                    open=float(b["open"]),
                    high=float(b["high"]),
                    low=float(b["low"]),
                    close=float(b["close"]),
                    tick_volume=int(b.get("tick_volume", 0)),
                    spread=int(b.get("spread", 0)),
                ))
            except (KeyError, ValueError) as e:
                continue
        return bars

    def _cache_key(self, symbol: str, timeframe: TF, start: datetime, end: datetime) -> str:
        """Generate a deterministic cache key."""
        key_str = f"{symbol}_{int(timeframe)}_{start.isoformat()}_{end.isoformat()}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def _load_cache(self, key: str) -> Optional[list[Bar]]:
        """Load cached bars from disk."""
        cache_file = self.cache_dir / f"{key}.json"
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, "r") as f:
                raw = json.load(f)
            return self._parse_bars(raw)
        except Exception:
            return None

    def _save_cache(self, key: str, bars: list[Bar]):
        """Save bars to disk cache."""
        cache_file = self.cache_dir / f"{key}.json"
        try:
            data = [
                {
                    "time": b.time.isoformat(),
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "tick_volume": b.tick_volume,
                    "spread": b.spread,
                }
                for b in bars
            ]
            with open(cache_file, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"[MT5Client] Cache save error: {e}")

    @staticmethod
    def _default_symbols() -> list[str]:
        """Fallback Exness forex symbol list."""
        return [
            "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD",
            "NZDUSD", "USDCAD", "EURGBP", "EURJPY", "GBPJPY",
            "AUDJPY", "EURAUD", "EURCHF", "GBPCHF", "GBPAUD",
            "AUDNZD", "AUDCAD", "NZDJPY", "CADJPY", "CHFJPY",
            "EURCAD", "EURNZD", "GBPCAD", "GBPNZD", "USDSGD",
            "XAUUSD", "XAGUSD",
        ]

    def close(self):
        """Close the HTTP client."""
        self._client.close()


from backtester.connectors.local_history_client import (  # noqa: E402
    DEFAULT_HISTORY_PATH,
    LocalHistoryClient,
)
from backtester.connectors.synthetic_client import SyntheticDataClient  # noqa: E402
from backtester.connectors.data_client_factory import (  # noqa: E402
    default_history_path,
    get_data_client,
)

__all__ = [
    "MT5Client",
    "LocalHistoryClient",
    "SyntheticDataClient",
    "DEFAULT_HISTORY_PATH",
    "default_history_path",
    "get_data_client",
]
