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

TF_TO_FOLDER: dict[TF, str] = {
    TF.M1: "1m",
    TF.M2: "2m",
    TF.M3: "3m",
    TF.M5: "5m",
    TF.M10: "10m",
    TF.M15: "15m",
    TF.M30: "30m",
    TF.H1: "1h",
    TF.H2: "2h",
    TF.H4: "4h",
    TF.H6: "6h",
    TF.H8: "8h",
    TF.H12: "12h",
    TF.D1: "1d",
    TF.W1: "1w",
    TF.MN1: "1mo",
}

FOLDER_TO_TF: dict[str, TF] = {folder: tf for tf, folder in TF_TO_FOLDER.items()}

FILENAME_RANGE_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV from local Exness structured history CSV files."""

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
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
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
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return []
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return []
        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return []
        all_bars: list[Bar] = []
        for csv_path in csv_files:
            all_bars.extend(self._read_csv_file(csv_path))
        all_bars.sort(key=lambda b: b.time)
        return self._dedupe_bars(all_bars)

    def _read_csv_file(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    bar = self._parse_row(row)
                    if bar is not None:
                        bars.append(bar)
        except OSError:
            return []
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

    @staticmethod
    def parse_filename_range(filename: str) -> tuple[Optional[datetime], Optional[datetime]]:
        match = FILENAME_RANGE_RE.match(filename)
        if not match:
            return None, None
        start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return start, end
