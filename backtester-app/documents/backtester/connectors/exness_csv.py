"""
Exness structured CSV history reader.
Reads OHLCV from local folder layout: {root}/{SYMBOL}/{tf_folder}/*.csv
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

FILENAME_RANGE_RE = re.compile(
    r"(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Local Exness CSV data client."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF], list[Bar]] = {}

    def path_exists(self) -> bool:
        return self.data_root.is_dir()

    def get_symbols(self) -> list[str]:
        if not self.path_exists():
            return []
        symbols = []
        for entry in sorted(self.data_root.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                symbols.append(entry.name.upper())
        return symbols

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder_name = TF_TO_FOLDER.get(timeframe)
        if not folder_name:
            return None
        tf_dir = self.data_root / symbol.upper() / folder_name
        if not tf_dir.is_dir():
            return None
        files = sorted(tf_dir.glob("*.csv"))
        return files[0] if files else None

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
            start, end = self._parse_filename_range(csv_path)
            bars = self._load_csv(csv_path)
            if bars:
                starts.append(bars[0].time if start is None else start)
                ends.append(bars[-1].time if end is None else end)
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
            csv_path = self._find_csv_file(symbol, timeframe)
            if not csv_path:
                self._cache[cache_key] = []
            else:
                self._cache[cache_key] = self._load_csv(csv_path)

        all_bars = self._cache[cache_key]
        if not all_bars:
            return []

        start_utc = self._ensure_utc(start)
        end_utc = self._ensure_utc(end)
        return [b for b in all_bars if start_utc <= b.time <= end_utc]

    def has_timeframes(self, symbol: str, required_timeframes: list[TF]) -> bool:
        for tf in required_timeframes:
            if not self._find_csv_file(symbol, tf):
                return False
        return True

    def _parse_filename_range(self, path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = FILENAME_RANGE_RE.match(path.name)
        if not match:
            return None, None
        start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
        return start, end

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
            print(f"[ExnessCSVClient] Failed to read {path}: {exc}")
            return []
        bars.sort(key=lambda b: b.time)
        return bars

    def _row_to_bar(self, row: dict) -> Optional[Bar]:
        time_raw = row.get("time_utc") or row.get("time")
        if not time_raw:
            return None
        try:
            dt = datetime.fromisoformat(str(time_raw).replace("Z", "+00:00"))
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
    def _ensure_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def tf_duration(timeframe: TF) -> "datetime.timedelta":
        from datetime import timedelta

        return timedelta(minutes=tf_to_minutes(timeframe))
