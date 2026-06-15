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
        symbols = []
        for entry in sorted(self.data_root.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                symbols.append(entry.name.upper())
        return symbols

    def _csv_path(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return None
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return None
        csv_files = sorted(tf_dir.glob(f"{symbol.upper()}_{folder}_*.csv"))
        if not csv_files:
            csv_files = sorted(tf_dir.glob("*.csv"))
        return csv_files[0] if csv_files else None

    def _parse_datetime(self, value: str) -> datetime:
        value = value.strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    def _load_file(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with open(path, newline="", encoding="utf-8") as handle:
            header = handle.readline().strip().lower()
            if not header:
                return []
            columns = [c.strip() for c in header.split(",")]
            time_idx = columns.index("time_utc") if "time_utc" in columns else columns.index("time")
            for line in handle:
                parts = line.strip().split(",")
                if len(parts) < 5:
                    continue
                try:
                    bars.append(
                        Bar(
                            time=self._parse_datetime(parts[time_idx]),
                            open=float(parts[columns.index("open")]),
                            high=float(parts[columns.index("high")]),
                            low=float(parts[columns.index("low")]),
                            close=float(parts[columns.index("close")]),
                            tick_volume=int(float(parts[columns.index("tick_volume")])),
                            spread=int(float(parts[columns.index("spread")])) if "spread" in columns else 0,
                        )
                    )
                except (ValueError, IndexError):
                    continue
        bars.sort(key=lambda b: b.time)
        return bars

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe)
        if cache_key not in self._cache:
            path = self._csv_path(symbol, timeframe)
            if path is None:
                return []
            self._cache[cache_key] = self._load_file(path)

        all_bars = self._cache[cache_key]
        return [b for b in all_bars if start <= b.time <= end]

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        return self._csv_path(symbol, timeframe) is not None

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> Optional[tuple[datetime, datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            path = self._csv_path(symbol, tf)
            if path is None:
                return None
            match = _FILENAME_RE.match(path.name)
            if match:
                starts.append(datetime.strptime(match.group("start"), "%Y-%m-%d"))
                ends.append(datetime.strptime(match.group("end"), "%Y-%m-%d"))
                continue
            bars = self._load_file(path)
            if not bars:
                return None
            starts.append(bars[0].time)
            ends.append(bars[-1].time)
        return min(starts), max(ends)
