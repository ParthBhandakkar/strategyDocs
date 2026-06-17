"""
Local Exness structured CSV history reader.
"""

from __future__ import annotations

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

_FILENAME_RE = re.compile(
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
            start, end = self._file_date_range(symbol, tf)
            if start and end:
                starts.append(start)
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
            self._cache[cache_key] = self._load_symbol_tf(symbol, timeframe)
        bars = self._cache[cache_key]
        if not bars:
            return []
        return [b for b in bars if start <= b.time <= end]

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return []
        tf_dir = self.data_root / symbol / folder
        if not tf_dir.is_dir():
            return []
        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return []
        all_bars: list[Bar] = []
        for csv_path in csv_files:
            all_bars.extend(self._parse_csv(csv_path))
        all_bars.sort(key=lambda b: b.time)
        return self._dedupe_bars(all_bars)

    def _parse_csv(self, path: Path) -> list[Bar]:
        import csv

        bars: list[Bar] = []
        try:
            with open(path, newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    ts_raw = row.get("time_utc") or row.get("time")
                    if not ts_raw:
                        continue
                    dt = self._parse_timestamp(ts_raw)
                    if dt is None:
                        continue
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
        except OSError:
            return []
        return bars

    @staticmethod
    def _parse_timestamp(value: str) -> Optional[datetime]:
        value = value.strip()
        if not value:
            return None
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    def _file_date_range(
        self,
        symbol: str,
        timeframe: TF,
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return None, None
        tf_dir = self.data_root / symbol / folder
        if not tf_dir.is_dir():
            return None, None

        file_start: Optional[datetime] = None
        file_end: Optional[datetime] = None
        for csv_path in tf_dir.glob("*.csv"):
            match = _FILENAME_RE.match(csv_path.name)
            if match:
                try:
                    start = datetime.strptime(match.group("start"), "%Y-%m-%d")
                    end = datetime.strptime(match.group("end"), "%Y-%m-%d")
                    file_start = start if file_start is None else min(file_start, start)
                    file_end = end if file_end is None else max(file_end, end)
                except ValueError:
                    continue

        bars = self._load_symbol_tf(symbol, timeframe)
        if bars:
            bar_start = bars[0].time
            bar_end = bars[-1].time
            file_start = bar_start if file_start is None else min(file_start, bar_start)
            file_end = bar_end if file_end is None else max(file_end, bar_end)
        return file_start, file_end

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
