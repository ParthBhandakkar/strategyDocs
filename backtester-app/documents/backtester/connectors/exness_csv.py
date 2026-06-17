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
from backtester.core.timeframes import TF, tf_from_folder, tf_to_folder

_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV bars from local Exness structured history CSV files."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF, str, str], list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        return sorted(
            p.name
            for p in self.data_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            path = self._find_csv(symbol, tf)
            if path is None:
                continue
            file_start, file_end = self._parse_filename_dates(path)
            if file_start:
                starts.append(file_start)
            if file_end:
                ends.append(file_end)
            if not file_start or not file_end:
                bars = self._load_file(path)
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
        path = self._find_csv(symbol, timeframe)
        if path is None:
            return []

        cache_key = (symbol, timeframe, start.isoformat(), end.isoformat())
        if cache_key in self._cache:
            return self._cache[cache_key]

        bars = self._load_file(path)
        filtered = [b for b in bars if start <= b.time <= end]
        self._cache[cache_key] = filtered
        return filtered

    def _find_csv(self, symbol: str, timeframe: TF) -> Optional[Path]:
        tf_folder = tf_to_folder(timeframe)
        tf_dir = self.data_root / symbol / tf_folder
        if not tf_dir.is_dir():
            return None
        files = sorted(tf_dir.glob(f"{symbol}_{tf_folder}_*.csv"))
        return files[0] if files else None

    def _load_file(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                bar = self._parse_row(row)
                if bar is not None:
                    bars.append(bar)
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

    def _parse_filename_dates(self, path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = _FILENAME_RE.match(path.name)
        if not match:
            return None, None
        start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
        return start, end

    def symbol_has_timeframes(self, symbol: str, required_timeframes: list[TF]) -> bool:
        return all(self._find_csv(symbol, tf) is not None for tf in required_timeframes)
