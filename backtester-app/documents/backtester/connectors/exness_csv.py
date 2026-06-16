"""
Exness CSV Client — reads local structured OHLCV history from disk.
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

_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Local CSV data client for Exness structured history."""

    def __init__(self, data_root: str):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF, str, str], list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        symbols = []
        for entry in sorted(self.data_root.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                symbols.append(entry.name.upper())
        return symbols

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return None
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return None
        csv_files = sorted(tf_dir.glob("*.csv"))
        return csv_files[0] if csv_files else None

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            csv_path = self._find_csv_file(symbol, tf)
            if not csv_path:
                continue
            file_start, file_end = self._parse_filename_dates(csv_path)
            bars = self._load_csv(csv_path)
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)
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
        cache_key = (
            symbol.upper(),
            timeframe,
            start.isoformat(),
            end.isoformat(),
        )
        if cache_key in self._cache:
            return self._cache[cache_key]

        csv_path = self._find_csv_file(symbol, timeframe)
        if not csv_path:
            return []

        all_bars = self._load_csv(csv_path)
        filtered = [b for b in all_bars if start <= b.time <= end]
        self._cache[cache_key] = filtered
        return filtered

    def _parse_filename_dates(self, path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = _FILENAME_RE.match(path.name)
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

    def _load_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(path, newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    bar = self._row_to_bar(row)
                    if bar:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Error reading {path}: {exc}")
        bars.sort(key=lambda b: b.time)
        return bars

    def _row_to_bar(self, row: dict[str, str]) -> Optional[Bar]:
        time_str = row.get("time_utc") or row.get("time")
        if not time_str:
            return None
        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
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
