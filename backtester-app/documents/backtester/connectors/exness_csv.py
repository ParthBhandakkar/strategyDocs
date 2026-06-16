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
from backtester.core.timeframes import TF, tf_folder_name, tf_from_folder

_FILENAME_RE = re.compile(
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
        symbols = []
        for entry in sorted(self.data_root.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                symbols.append(entry.name.upper())
        return symbols

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
            if start:
                starts.append(start)
            if end:
                ends.append(end)
            if not start or not end:
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

        all_bars = self._cache[cache_key]
        if not all_bars:
            return []

        start_utc = self._ensure_utc(start)
        end_utc = self._ensure_utc(end)
        return [b for b in all_bars if start_utc <= b.time <= end_utc]

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        sym = symbol.upper()
        tf_dir = self.data_root / sym / tf_folder_name(timeframe)
        if not tf_dir.is_dir():
            return None
        candidates = sorted(tf_dir.glob(f"{sym}_{tf_folder_name(timeframe)}_*.csv"))
        if not candidates:
            return None
        return candidates[0]

    def _load_file(self, file_path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(file_path, newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    bar = self._parse_row(row)
                    if bar is not None:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed to read {file_path}: {exc}")
            return []
        bars.sort(key=lambda b: b.time)
        return bars

    def _parse_row(self, row: dict[str, str]) -> Optional[Bar]:
        time_raw = row.get("time_utc") or row.get("time")
        if not time_raw:
            return None
        try:
            dt = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
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
        match = _FILENAME_RE.match(file_path.name)
        if not match:
            return None, None
        try:
            start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            return start, end
        except ValueError:
            return None, None

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
