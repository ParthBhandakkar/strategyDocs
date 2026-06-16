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

FOLDER_BY_TF: dict[TF, str] = {tf: folder for folder, tf in TF_FOLDER_MAP.items()}

DATE_RANGE_RE = re.compile(
    r"(?P<symbol>[^_]+)_(?P<tf>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV from structured Exness CSV history on disk."""

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
            if file_start:
                starts.append(file_start)
            if file_end:
                ends.append(file_end)
            if not file_start or not file_end:
                bars = self._load_file(csv_path, tf)
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
            csv_path = self._find_csv_file(symbol, timeframe)
            if not csv_path:
                self._cache[cache_key] = []
            else:
                self._cache[cache_key] = self._load_file(csv_path, timeframe)

        all_bars = self._cache.get(cache_key, [])
        if not all_bars:
            return []

        start_utc = self._ensure_utc(start)
        end_utc = self._ensure_utc(end)
        return [b for b in all_bars if start_utc <= b.time <= end_utc]

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        return self._find_csv_file(symbol, timeframe) is not None

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder = FOLDER_BY_TF.get(timeframe)
        if not folder:
            return None
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return None
        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return None
        return csv_files[-1]

    def _load_file(self, csv_path: Path, timeframe: TF) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with csv_path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    bar = self._parse_row(row)
                    if bar:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed to read {csv_path}: {exc}")
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

    def _parse_filename_dates(self, csv_path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = DATE_RANGE_RE.match(csv_path.name)
        if not match:
            return None, None
        start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
        return start, end

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
