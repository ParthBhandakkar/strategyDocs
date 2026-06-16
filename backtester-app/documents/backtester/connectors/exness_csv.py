"""
Local Exness structured CSV history reader.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes

FOLDER_TO_TF: dict[str, TF] = {
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

TF_TO_FOLDER: dict[TF, str] = {value: key for key, value in FOLDER_TO_TF.items()}

FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV from local Exness structured history folders."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF], list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        return sorted(
            item.name
            for item in self.data_root.iterdir()
            if item.is_dir() and not item.name.startswith(".")
        )

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            file_path = self._find_csv_file(symbol, tf)
            if file_path is None:
                continue
            start, end = self._parse_filename_dates(file_path)
            if start is not None:
                starts.append(start)
            if end is not None:
                ends.append(end)
            if start is None or end is None:
                bars = self._load_file(file_path)
                if bars:
                    starts.append(bars[0].time)
                    ends.append(bars[-1].time)
        if not starts or not ends:
            return None, None
        return min(starts), max(ends)

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe)
        if cache_key not in self._cache:
            file_path = self._find_csv_file(symbol, timeframe)
            if file_path is None:
                self._cache[cache_key] = []
            else:
                self._cache[cache_key] = self._load_file(file_path)

        bars = self._cache[cache_key]
        if not bars:
            return []

        start_naive = self._as_naive(start)
        end_naive = self._as_naive(end)
        return [bar for bar in bars if start_naive <= self._as_naive(bar.time) <= end_naive]

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder = TF_TO_FOLDER.get(timeframe)
        if folder is None:
            return None
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return None
        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return None
        return csv_files[0]

    def _load_file(self, file_path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with file_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                bar = self._parse_row(row)
                if bar is not None:
                    bars.append(bar)
        bars.sort(key=lambda item: item.time)
        return bars

    def _parse_row(self, row: dict[str, str]) -> Optional[Bar]:
        time_raw = row.get("time_utc") or row.get("time")
        if not time_raw:
            return None
        try:
            dt = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
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

    def _parse_filename_dates(self, file_path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = FILENAME_RE.match(file_path.name)
        if not match:
            return None, None
        start = datetime.strptime(match.group("start"), "%Y-%m-%d")
        end = datetime.strptime(match.group("end"), "%Y-%m-%d")
        return start, end.replace(hour=23, minute=59, second=59)

    @staticmethod
    def _as_naive(value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
