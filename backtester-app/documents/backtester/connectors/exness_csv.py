"""
Local Exness structured CSV history reader.
Reads OHLCV from {data_root}/{SYMBOL}/{tf_folder}/*.csv
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

_FILENAME_RE = re.compile(
    r"(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads local Exness structured history CSV files."""

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

    def _resolve_csv_path(self, symbol: str, timeframe: TF) -> Optional[Path]:
        sym_dir = self.data_root / symbol.upper()
        tf_folder = TF_TO_FOLDER.get(timeframe)
        if not tf_folder:
            return None
        tf_dir = sym_dir / tf_folder
        if not tf_dir.is_dir():
            return None
        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return None
        return csv_files[-1]

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            path = self._resolve_csv_path(symbol, tf)
            if path is None:
                return None, None
            file_start, file_end = self._parse_filename_dates(path)
            bars = self._load_csv(path)
            if not bars:
                return None, None
            starts.append(file_start or bars[0].time)
            ends.append(file_end or bars[-1].time)
        if not starts or not ends:
            return None, None
        return max(starts), min(ends)

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe)
        if cache_key not in self._cache:
            path = self._resolve_csv_path(symbol, timeframe)
            if path is None:
                return []
            self._cache[cache_key] = self._load_csv(path)

        all_bars = self._cache[cache_key]
        if not all_bars:
            return []

        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        return [b for b in all_bars if start_utc <= _ensure_utc(b.time) <= end_utc]

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        return self._resolve_csv_path(symbol, timeframe) is not None

    def _parse_filename_dates(self, path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = _FILENAME_RE.match(path.name)
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
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    bar = _row_to_bar(row)
                    if bar:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed to read {path}: {exc}")
            return []
        bars.sort(key=lambda b: b.time)
        return bars


def _row_to_bar(row: dict[str, str]) -> Optional[Bar]:
    time_raw = row.get("time_utc") or row.get("time")
    if not time_raw:
        return None
    try:
        ts = time_raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
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


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
