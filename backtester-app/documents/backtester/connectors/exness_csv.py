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
from backtester.core.timeframes import TF, tf_to_folder, folder_to_tf


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

    def _find_csv_file(self, symbol: str, tf: TF) -> Optional[Path]:
        folder = self.data_root / symbol.upper() / tf_to_folder(tf)
        if not folder.is_dir():
            return None
        csv_files = sorted(folder.glob(f"{symbol.upper()}_{tf_to_folder(tf)}_*.csv"))
        if not csv_files:
            csv_files = sorted(folder.glob("*.csv"))
        return csv_files[0] if csv_files else None

    def _parse_filename_dates(self, path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = re.search(
            r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$",
            path.name,
        )
        if not match:
            return None, None
        start = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group(2), "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
        return start, end

    def _load_all_bars(self, symbol: str, tf: TF) -> list[Bar]:
        key = (symbol.upper(), tf)
        if key in self._cache:
            return self._cache[key]

        csv_path = self._find_csv_file(symbol, tf)
        if csv_path is None:
            self._cache[key] = []
            return []

        bars: list[Bar] = []
        with open(csv_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                try:
                    time_raw = row.get("time_utc") or row.get("time")
                    if not time_raw:
                        continue
                    time_raw = time_raw.strip()
                    if time_raw.endswith("Z"):
                        time_raw = time_raw[:-1] + "+00:00"
                    dt = datetime.fromisoformat(time_raw)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)

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

        bars.sort(key=lambda bar: bar.time)
        self._cache[key] = bars
        return bars

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        all_bars = self._load_all_bars(symbol, timeframe)
        if not all_bars:
            return []

        start_utc = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        end_utc = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        return [bar for bar in all_bars if start_utc <= bar.time <= end_utc]

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            csv_path = self._find_csv_file(symbol, tf)
            if csv_path is None:
                continue
            file_start, file_end = self._parse_filename_dates(csv_path)
            bars = self._load_all_bars(symbol, tf)
            if bars:
                starts.append(file_start or bars[0].time)
                ends.append(file_end or bars[-1].time)
        if not starts or not ends:
            return None, None
        return min(starts), max(ends)

    def has_timeframes(self, symbol: str, required_timeframes: list[TF]) -> bool:
        for tf in required_timeframes:
            if self._find_csv_file(symbol, tf) is None:
                return False
        return True

    def available_timeframes(self, symbol: str) -> list[TF]:
        symbol_dir = self.data_root / symbol.upper()
        if not symbol_dir.is_dir():
            return []
        found: list[TF] = []
        for tf_dir in symbol_dir.iterdir():
            if tf_dir.is_dir():
                try:
                    found.append(folder_to_tf(tf_dir.name))
                except ValueError:
                    continue
        return found
