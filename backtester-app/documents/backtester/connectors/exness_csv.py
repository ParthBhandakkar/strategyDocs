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
from backtester.core.timeframes import TF, tf_from_string, tf_to_folder

_DATE_RANGE_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV bars from local Exness structured history folders."""

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
            bars = self.get_bars(symbol, tf)
            if not bars:
                continue
            starts.append(bars[0].time)
            ends.append(bars[-1].time)
        if not starts or not ends:
            return None, None
        return min(starts), max(ends)

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._load_symbol_tf(symbol, timeframe)
        bars = self._cache[cache_key]
        if start is None and end is None:
            return list(bars)
        filtered: list[Bar] = []
        for bar in bars:
            if start is not None and bar.time < start:
                continue
            if end is not None and bar.time > end:
                continue
            filtered.append(bar)
        return filtered

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        tf_folder = tf_to_folder(timeframe)
        tf_dir = self.data_root / symbol.upper() / tf_folder
        if not tf_dir.is_dir():
            return []
        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return []
        bars: list[Bar] = []
        for csv_file in csv_files:
            bars.extend(self._read_csv_file(csv_file))
        bars.sort(key=lambda b: b.time)
        return self._dedupe_bars(bars)

    def _read_csv_file(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    bar = self._parse_row(row)
                    if bar is not None:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed reading {path}: {exc}")
        return bars

    def _parse_row(self, row: dict[str, str]) -> Bar | None:
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
    def _dedupe_bars(bars: list[Bar]) -> list[Bar]:
        seen: set[datetime] = set()
        unique: list[Bar] = []
        for bar in bars:
            if bar.time in seen:
                continue
            seen.add(bar.time)
            unique.append(bar)
        return unique

    def parse_filename_range(self, filename: str) -> tuple[Optional[datetime], Optional[datetime]]:
        match = _DATE_RANGE_RE.match(filename)
        if not match:
            return None, None
        start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
        return start, end
