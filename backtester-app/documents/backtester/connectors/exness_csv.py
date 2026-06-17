"""
Local Exness structured CSV history reader.
Reads OHLCV from: {data_root}/{SYMBOL}/{tf_folder}/*.csv
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

TF_TO_FOLDER: dict[TF, str] = {v: k for k, v in FOLDER_TO_TF.items()}

DATE_RANGE_RE = re.compile(
    r"(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads local Exness CSV history with in-memory caching."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF], list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        symbols = sorted(
            p.name
            for p in self.data_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
        return symbols

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return False
        tf_dir = self.data_root / symbol / folder
        return tf_dir.is_dir() and any(tf_dir.glob("*.csv"))

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            for csv_file in self._csv_files(symbol, tf):
                file_start, file_end = self._parse_filename_dates(csv_file, symbol, tf)
                bars = self._load_csv(csv_file)
                if bars:
                    starts.append(file_start or bars[0].time)
                    ends.append(file_end or bars[-1].time)
                elif file_start and file_end:
                    starts.append(file_start)
                    ends.append(file_end)
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
        cache_key = (symbol, timeframe)
        if cache_key not in self._cache:
            all_bars: list[Bar] = []
            for csv_file in self._csv_files(symbol, timeframe):
                all_bars.extend(self._load_csv(csv_file))
            all_bars.sort(key=lambda b: b.time)
            self._cache[cache_key] = all_bars

        start_naive = self._to_utc(start)
        end_naive = self._to_utc(end)
        return [
            b
            for b in self._cache[cache_key]
            if start_naive <= self._to_utc(b.time) <= end_naive
        ]

    def _csv_files(self, symbol: str, timeframe: TF) -> list[Path]:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return []
        tf_dir = self.data_root / symbol / folder
        if not tf_dir.is_dir():
            return []
        return sorted(tf_dir.glob("*.csv"))

    def _parse_filename_dates(
        self,
        csv_file: Path,
        symbol: str,
        timeframe: TF,
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        match = DATE_RANGE_RE.match(csv_file.name)
        if not match:
            return None, None
        try:
            start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            return start, end
        except ValueError:
            return None, None

    def _load_csv(self, csv_file: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(csv_file, newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    bar = self._parse_row(row)
                    if bar:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed to read {csv_file}: {exc}")
        return bars

    def _parse_row(self, row: dict[str, str]) -> Optional[Bar]:
        time_raw = row.get("time_utc") or row.get("time")
        if not time_raw:
            return None
        try:
            dt = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
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

    @staticmethod
    def _to_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
