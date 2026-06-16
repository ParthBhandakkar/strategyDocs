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
from backtester.core.timeframes import TF, tf_from_folder

_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV from structured Exness CSV history folders."""

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
            path = self._find_csv_file(symbol, tf)
            if path is None:
                continue
            file_start, file_end = self._parse_filename_dates(path)
            if file_start and file_end:
                starts.append(file_start)
                ends.append(file_end)
                continue
            bars = self._load_csv(path, tf)
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
            path = self._find_csv_file(symbol, timeframe)
            if path is None:
                self._cache[cache_key] = []
            else:
                self._cache[cache_key] = self._load_csv(path, timeframe)

        all_bars = self._cache.get(cache_key, [])
        if not all_bars:
            return []

        start_utc = self._ensure_utc(start)
        end_utc = self._ensure_utc(end)
        return [b for b in all_bars if start_utc <= self._ensure_utc(b.time) <= end_utc]

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        return self._find_csv_file(symbol, timeframe) is not None

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder = self._tf_folder(timeframe)
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return None
        matches = sorted(tf_dir.glob(f"{symbol.upper()}_{folder}_*.csv"))
        if not matches:
            matches = sorted(tf_dir.glob("*.csv"))
        return matches[0] if matches else None

    def _tf_folder(self, timeframe: TF) -> str:
        for folder in (
            "1m", "2m", "3m", "5m", "10m", "15m", "30m",
            "1h", "2h", "4h", "6h", "8h", "12h", "1d", "1w", "1mo",
        ):
            try:
                if tf_from_folder(folder) == timeframe:
                    return folder
            except ValueError:
                continue
        raise ValueError(f"No folder mapping for timeframe {timeframe}")

    def _load_csv(self, path: Path, timeframe: TF) -> list[Bar]:
        bars: list[Bar] = []
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ts_raw = row.get("time_utc") or row.get("time")
                if not ts_raw:
                    continue
                bar_time = self._parse_time(ts_raw)
                if bar_time is None:
                    continue
                try:
                    bars.append(
                        Bar(
                            time=bar_time,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            tick_volume=int(float(row.get("tick_volume") or 0)),
                            spread=int(float(row.get("spread") or 0)),
                        )
                    )
                except (KeyError, ValueError):
                    continue
        bars.sort(key=lambda b: b.time)
        return bars

    def _parse_filename_dates(self, path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = _FILENAME_RE.match(path.name)
        if not match:
            return None, None
        start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
        return start, end

    @staticmethod
    def _parse_time(value: str) -> Optional[datetime]:
        value = value.strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
