"""
Local Exness OHLCV history reader.

Expected layout under LOCAL_HISTORY_PATH:
  {SYMBOL}/{TF}.csv
  {SYMBOL}/{TF}.json
  {SYMBOL}/{TF}.parquet
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
from backtester.connectors.data_client import DataClient


class LocalHistoryClient:
    """Reads OHLCV bars from a local structured history directory."""

    def __init__(self, history_path: str | None = None):
        self.history_path = Path(
            history_path or os.getenv("LOCAL_HISTORY_PATH", "")
        )
        if not self.history_path.exists():
            raise FileNotFoundError(
                f"Local history path not found: {self.history_path}"
            )

    def get_symbols(self) -> list[str]:
        return sorted(
            p.name for p in self.history_path.iterdir() if p.is_dir()
        )

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        del use_cache  # Local reads are already cached on disk.
        file_path = self._resolve_file(symbol, timeframe)
        if file_path is None:
            return []

        bars = self._load_file(file_path)
        return [b for b in bars if start <= b.time <= end]

    def close(self) -> None:
        pass

    def _resolve_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        tf_label = tf_short(timeframe)
        symbol_dir = self.history_path / symbol.upper()
        candidates = [
            symbol_dir / f"{tf_label}.csv",
            symbol_dir / f"{tf_label}.json",
            symbol_dir / f"{tf_label}.parquet",
            self.history_path / f"{symbol.upper()}_{tf_label}.csv",
        ]
        for path in candidates:
            if path.exists():
                return path
        return None

    def _load_file(self, path: Path) -> list[Bar]:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return self._parse_csv(path)
        if suffix == ".json":
            return self._parse_json(path)
        if suffix == ".parquet":
            return self._parse_parquet(path)
        return []

    def _parse_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                bar = self._row_to_bar(row)
                if bar:
                    bars.append(bar)
        return sorted(bars, key=lambda b: b.time)

    def _parse_json(self, path: Path) -> list[Bar]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("bars", [])
        bars = [self._row_to_bar(row) for row in rows]
        return sorted([b for b in bars if b], key=lambda b: b.time)

    def _parse_parquet(self, path: Path) -> list[Bar]:
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "pandas is required to read parquet history files"
            ) from exc

        frame = pd.read_parquet(path)
        bars: list[Bar] = []
        for _, row in frame.iterrows():
            bar = self._row_to_bar(row.to_dict())
            if bar:
                bars.append(bar)
        return sorted(bars, key=lambda b: b.time)

    def _row_to_bar(self, row: dict) -> Optional[Bar]:
        time_value = (
            row.get("time")
            or row.get("timestamp")
            or row.get("datetime")
            or row.get("date")
        )
        if time_value is None:
            return None

        dt = self._parse_time(time_value)
        try:
            return Bar(
                time=dt,
                open=float(row.get("open", row.get("Open", 0))),
                high=float(row.get("high", row.get("High", 0))),
                low=float(row.get("low", row.get("Low", 0))),
                close=float(row.get("close", row.get("Close", 0))),
                tick_volume=int(
                    row.get("tick_volume", row.get("volume", row.get("Volume", 0)))
                ),
                spread=int(row.get("spread", 0)),
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_time(value: object) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
