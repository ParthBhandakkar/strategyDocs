"""
Local Exness structured CSV history reader.
"""

from __future__ import annotations

import csv
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_folder_name, tf_from_folder

_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV from local Exness structured history folders."""

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
            if start and bar.time < start:
                continue
            if end and bar.time > end:
                continue
            filtered.append(bar)
        return filtered

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        tf_dir = self.data_root / symbol.upper() / tf_folder_name(timeframe)
        if not tf_dir.is_dir():
            return []
        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return []
        bars: list[Bar] = []
        for csv_path in csv_files:
            bars.extend(self._read_csv(csv_path))
        bars.sort(key=lambda b: b.time)
        deduped: dict[datetime, Bar] = {}
        for bar in bars:
            deduped[bar.time] = bar
        return [deduped[t] for t in sorted(deduped)]

    def _read_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ts_raw = row.get("time_utc") or row.get("time")
                if not ts_raw:
                    continue
                dt = self._parse_time(ts_raw)
                if dt is None:
                    continue
                try:
                    bars.append(
                        Bar(
                            time=dt,
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
        return bars

    @staticmethod
    def _parse_time(value: str) -> datetime | None:
        value = value.strip()
        if not value:
            return None
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def parse_filename_dates(path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = _FILENAME_RE.match(path.name)
        if not match:
            return None, None
        start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return start, end


def resolve_data_root(cli_root: str | None = None) -> str | None:
    """Resolve history root: CLI > env > Windows default."""
    if cli_root:
        root = Path(cli_root)
        if root.is_dir() and _has_symbol_data(root):
            return str(root)
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        root = Path(env_path)
        if root.is_dir() and _has_symbol_data(root):
            return str(root)
    default = Path(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history")
    if default.is_dir() and _has_symbol_data(default):
        return str(default)
    return None


def _has_symbol_data(root: Path) -> bool:
    for child in root.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            return True
    return False
