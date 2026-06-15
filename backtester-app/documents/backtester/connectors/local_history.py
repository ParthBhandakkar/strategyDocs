"""
Local Exness OHLCV history client.

Expected layout under LOCAL_HISTORY_PATH:
  {SYMBOL}/{TF}.csv
  {SYMBOL}/{TF}.json
  {SYMBOL}_{TF}.csv
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_short


class LocalHistoryClient:
    """Reads OHLCV from the user's downloaded Exness history folder."""

    def __init__(self, history_path: str | Path | None = None):
        self.history_path = Path(
            history_path or os.getenv("LOCAL_HISTORY_PATH", "")
        )
        self._cache: dict[str, list[Bar]] = {}

    def health_check(self) -> dict:
        if self.history_path.exists():
            return {"status": "ok", "source": "local", "path": str(self.history_path)}
        return {"status": "missing", "source": "local", "path": str(self.history_path)}

    def get_symbols(self) -> list[str]:
        if not self.history_path.exists():
            return []
        symbols = []
        for entry in self.history_path.iterdir():
            if entry.is_dir():
                symbols.append(entry.name)
        return sorted(symbols)

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        cache_key = f"{symbol}_{int(timeframe)}_{start.isoformat()}_{end.isoformat()}"
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        all_bars = self._load_symbol_tf(symbol, timeframe)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        filtered = [b for b in all_bars if start <= b.time <= end]
        if use_cache:
            self._cache[cache_key] = filtered
        return filtered

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        tf_label = tf_short(timeframe)
        candidates = [
            self.history_path / symbol / f"{tf_label}.csv",
            self.history_path / symbol / f"{tf_label}.json",
            self.history_path / f"{symbol}_{tf_label}.csv",
            self.history_path / symbol.upper() / f"{tf_label}.csv",
        ]
        for path in candidates:
            if path.exists():
                if path.suffix == ".json":
                    return self._parse_json(path)
                return self._parse_csv(path)
        return []

    def _parse_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with path.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                bar = self._row_to_bar(row)
                if bar:
                    bars.append(bar)
        bars.sort(key=lambda b: b.time)
        return bars

    def _parse_json(self, path: Path) -> list[Bar]:
        with path.open(encoding="utf-8") as handle:
            raw = json.load(handle)
        if isinstance(raw, dict):
            raw = raw.get("bars", [])
        bars = []
        for item in raw:
            if isinstance(item, dict):
                bar = self._row_to_bar(item)
                if bar:
                    bars.append(bar)
        bars.sort(key=lambda b: b.time)
        return bars

    def _row_to_bar(self, row: dict) -> Optional[Bar]:
        time_key = next((k for k in row if k.lower() in {"time", "datetime", "date"}), None)
        if not time_key:
            return None
        try:
            raw_time = row[time_key]
            if isinstance(raw_time, (int, float)):
                dt = datetime.fromtimestamp(raw_time, tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            return Bar(
                time=dt,
                open=float(row.get("open", row.get("Open", 0))),
                high=float(row.get("high", row.get("High", 0))),
                low=float(row.get("low", row.get("Low", 0))),
                close=float(row.get("close", row.get("Close", 0))),
                tick_volume=int(float(row.get("tick_volume", row.get("volume", 0)) or 0)),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def close(self) -> None:
        return
