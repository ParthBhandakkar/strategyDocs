"""
Local Exness structured CSV history reader.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone, timedelta
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

_FILENAME_RANGE_RE = re.compile(
    r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV from local Exness structured history CSV files."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF], list[Bar]] = {}

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
            start, end = self._parse_file_range(path, symbol, tf)
            if start:
                starts.append(start)
            if end:
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
    ) -> list[Bar]:
        cache_key = (symbol, timeframe)
        if cache_key not in self._cache:
            path = self._find_csv(symbol, timeframe)
            if path is None:
                self._cache[cache_key] = []
            else:
                self._cache[cache_key] = self._load_csv(path)
        bars = self._cache[cache_key]
        if not bars:
            return []
        return [b for b in bars if start <= b.time <= end]

    def _find_csv(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder = TF_TO_FOLDER.get(timeframe)
        if folder is None:
            return None
        tf_dir = self.data_root / symbol / folder
        if not tf_dir.is_dir():
            return None
        files = sorted(tf_dir.glob(f"{symbol}_{folder}_*.csv"))
        return files[0] if files else None

    def _parse_file_range(
        self,
        path: Path,
        symbol: str,
        timeframe: TF,
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        match = _FILENAME_RANGE_RE.search(path.name)
        if match:
            start = datetime.fromisoformat(match.group(1)).replace(tzinfo=timezone.utc)
            end = datetime.fromisoformat(match.group(2)).replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            return start, end
        bars = self._load_csv(path)
        if not bars:
            return None, None
        return bars[0].time, bars[-1].time

    def _load_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(path, newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    bar = self._row_to_bar(row)
                    if bar is not None:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed to read {path}: {exc}")
            return []
        bars.sort(key=lambda b: b.time)
        return bars

    def _row_to_bar(self, row: dict[str, str]) -> Optional[Bar]:
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
                tick_volume=int(float(row.get("tick_volume") or row.get("real_volume") or 0)),
                spread=int(float(row.get("spread") or 0)),
            )
        except (KeyError, ValueError):
            return None

    @staticmethod
    def bar_close_time(bar: Bar, timeframe: TF) -> datetime:
        minutes = tf_to_minutes(timeframe)
        return bar.time + timedelta(minutes=minutes)
