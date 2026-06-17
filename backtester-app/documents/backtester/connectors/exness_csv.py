"""
Local Exness structured CSV history reader.
Reads OHLCV from {data_root}/{SYMBOL}/{tf_folder}/*.csv files.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from functools import lru_cache
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
    r"(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
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
    """Reads local Exness structured history CSV files."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF, str, str], list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        symbols = sorted(
            p.name
            for p in self.data_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
        return symbols

    def _csv_files(self, symbol: str, timeframe: TF) -> list[Path]:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return []
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return []
        return sorted(tf_dir.glob("*.csv"))

    def _parse_file(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                try:
                    ts = _parse_timestamp(row.get("time_utc") or row.get("time", ""))
                    bars.append(
                        Bar(
                            time=ts,
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

    def _file_date_range(self, path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = FILENAME_DATE_RE.match(path.name)
        if match:
            start = datetime.strptime(match.group("start"), "%Y-%m-%d")
            end = datetime.strptime(match.group("end"), "%Y-%m-%d")
            return start, end
        bars = self._parse_file(path)
        if not bars:
            return None, None
        return bars[0].time, bars[-1].time

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            files = self._csv_files(symbol, tf)
            if not files:
                return None, None
            for path in files:
                start, end = self._file_date_range(path)
                if start and end:
                    starts.append(start)
                    ends.append(end)
        if not starts or not ends:
            return None, None
        return min(starts), max(ends)

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe, start.isoformat(), end.isoformat())
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        all_bars: list[Bar] = []
        for path in self._csv_files(symbol, timeframe):
            all_bars.extend(self._parse_file(path))

        if not all_bars:
            return []

        all_bars.sort(key=lambda b: b.time)
        filtered = [b for b in all_bars if start <= b.time <= end]
        if use_cache:
            self._cache[cache_key] = filtered
        return filtered

    def symbol_has_timeframes(self, symbol: str, timeframes: list[TF]) -> bool:
        for tf in timeframes:
            if not self._csv_files(symbol, tf):
                return False
        return True
