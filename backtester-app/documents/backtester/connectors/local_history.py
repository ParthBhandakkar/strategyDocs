"""
Local Exness OHLCV reader — loads CSV history from structured disk layout.

Layout: {data_root}/{SYMBOL}/{timeframe_folder}/{SYMBOL}_{tf}_*.csv
Example: .../history/XAUUSD/1m/XAUUSD_1m_2010-09-26_2026-06-02.csv
"""

from __future__ import annotations

import csv
import os
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes

_DEFAULT_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"

_TF_FOLDER: dict[TF, str] = {
    TF.M1: "1m",
    TF.M2: "2m",
    TF.M3: "3m",
    TF.M5: "5m",
    TF.M10: "10m",
    TF.M15: "15m",
    TF.M30: "30m",
    TF.H1: "1h",
    TF.H2: "2h",
    TF.H4: "4h",
    TF.H6: "6h",
    TF.H8: "8h",
    TF.H12: "12h",
    TF.D1: "1d",
    TF.W1: "1w",
    TF.MN1: "1mo",
}


class LocalHistoryClient:
    """Reads OHLCV bars from on-disk Exness structured CSV history."""

    def __init__(self, data_root: str | None = None):
        self.data_root = Path(
            data_root or os.getenv("LOCAL_HISTORY_PATH", _DEFAULT_ROOT)
        )
        self._cache: dict[tuple[str, TF], list[Bar]] = {}

    def health_check(self) -> dict:
        if not self.data_root.is_dir():
            return {
                "status": "error",
                "error": f"Local history path not found: {self.data_root}",
            }
        symbols = self.get_symbols()
        return {
            "status": "ok",
            "source": "local",
            "data_root": str(self.data_root),
            "symbol_count": len(symbols),
        }

    def get_symbols(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        return sorted(
            p.name
            for p in self.data_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        key = (symbol.upper(), timeframe)
        if use_cache and key in self._cache:
            all_bars = self._cache[key]
        else:
            all_bars = self._load_symbol_tf(symbol.upper(), timeframe)
            self._cache[key] = all_bars

        if not all_bars:
            return []

        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        left = bisect_left(all_bars, start_utc, key=lambda b: b.time)
        right = bisect_right(all_bars, end_utc, key=lambda b: b.time)
        return all_bars[left:right]

    def close(self):
        self._cache.clear()

    def clear_cache(self):
        """Drop in-memory CSV caches between symbol runs."""
        self._cache.clear()

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        folder = _TF_FOLDER.get(timeframe)
        if not folder:
            print(f"[LocalHistoryClient] Unsupported timeframe: {timeframe}")
            return []

        tf_dir = self.data_root / symbol / folder
        if not tf_dir.is_dir():
            print(f"[LocalHistoryClient] No data dir: {tf_dir}")
            return []

        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            print(f"[LocalHistoryClient] No CSV in {tf_dir}")
            return []

        bars: list[Bar] = []
        for csv_path in csv_files:
            bars.extend(self._read_csv(csv_path))

        bars.sort(key=lambda b: b.time)
        return bars

    def _read_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                bar = _row_to_bar(row)
                if bar is not None:
                    bars.append(bar)
        return bars


def _row_to_bar(row: dict) -> Optional[Bar]:
    raw_time = row.get("time_utc") or row.get("time")
    if not raw_time:
        return None
    try:
        if raw_time.isdigit():
            dt = datetime.fromtimestamp(int(raw_time), tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None

    try:
        return Bar(
            time=dt,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            tick_volume=int(float(row.get("tick_volume") or 0)),
            spread=int(float(row.get("spread") or 0)),
        )
    except (KeyError, ValueError):
        return None


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
