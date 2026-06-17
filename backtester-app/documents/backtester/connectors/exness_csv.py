"""
Local Exness structured CSV history reader.
Reads OHLCV from {data_root}/{SYMBOL}/{tf_folder}/*.csv files.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes

TF_FOLDER_MAP: dict[str, TF] = {
    "1m": TF.M1,
    "2m": TF.M2,
    "3m": TF.M3,
    "5m": TF.M5,
    "10m": TF.M10,
    "15m": TF.M15,
    "30m": TF.M30,
    "1h": TF.H1,
    "2h": TF.H2,
    "4h": TF.H4,
    "6h": TF.H6,
    "8h": TF.H8,
    "12h": TF.H12,
    "1d": TF.D1,
    "1w": TF.W1,
    "1mo": TF.MN1,
}

TF_TO_FOLDER: dict[TF, str] = {v: k for k, v in TF_FOLDER_MAP.items()}

FILENAME_DATE_RE = re.compile(
    r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$"
)


def _parse_timestamp(value: str) -> datetime:
    value = value.strip()
    if not value:
        raise ValueError("empty timestamp")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class ExnessCSVClient:
    """Reads local Exness CSV history from a structured directory tree."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF], list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        symbols = [
            p.name
            for p in self.data_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ]
        return sorted(symbols)

    def _csv_path(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return None
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return None
        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return None
        return csv_files[0]

    def _load_file(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                try:
                    ts_raw = row.get("time_utc") or row.get("time") or ""
                    bars.append(
                        Bar(
                            time=_parse_timestamp(ts_raw),
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            tick_volume=int(float(row.get("tick_volume") or 0)),
                            spread=int(float(row.get("spread") or 0)),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    continue
        bars.sort(key=lambda b: b.time)
        return bars

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe)
        if cache_key not in self._cache:
            path = self._csv_path(symbol, timeframe)
            if path is None:
                self._cache[cache_key] = []
            else:
                self._cache[cache_key] = self._load_file(path)

        filtered = [b for b in self._cache[cache_key] if start <= b.time <= end]
        return filtered

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            path = self._csv_path(symbol, tf)
            if path is None:
                continue
            match = FILENAME_DATE_RE.search(path.name)
            if match:
                starts.append(datetime.fromisoformat(match.group(1)))
                ends.append(datetime.fromisoformat(match.group(2)))
                continue
            bars = self._load_file(path)
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)
        if not starts or not ends:
            return None, None
        return min(starts), max(ends)

    def has_timeframes(self, symbol: str, required_timeframes: list[TF]) -> bool:
        for tf in required_timeframes:
            if self._csv_path(symbol, tf) is None:
                return False
        return True
