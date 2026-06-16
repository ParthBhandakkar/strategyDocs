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
from backtester.core.timeframes import TF

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

FILENAME_DATE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$")


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

    def _tf_folder(self, timeframe: TF) -> Optional[str]:
        return TF_TO_FOLDER.get(timeframe)

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder = self._tf_folder(timeframe)
        if not folder:
            return None
        tf_dir = self.data_root / symbol / folder
        if not tf_dir.is_dir():
            return None
        files = sorted(tf_dir.glob(f"{symbol}_{folder}_*.csv"))
        if not files:
            files = sorted(tf_dir.glob("*.csv"))
        return files[0] if files else None

    def _parse_dt(self, value: str) -> datetime:
        value = value.strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    def _load_file(self, csv_path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with open(csv_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                time_key = "time_utc" if "time_utc" in row else "time"
                if time_key not in row:
                    continue
                try:
                    bars.append(
                        Bar(
                            time=self._parse_dt(row[time_key]),
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

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        cache_key = (symbol, timeframe)
        if cache_key not in self._cache:
            csv_path = self._find_csv_file(symbol, timeframe)
            if csv_path is None:
                self._cache[cache_key] = []
            else:
                self._cache[cache_key] = self._load_file(csv_path)

        return [b for b in self._cache[cache_key] if start <= b.time <= end]

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
            match = FILENAME_DATE_RE.search(csv_path.name)
            if match:
                starts.append(datetime.fromisoformat(match.group(1)))
                ends.append(datetime.fromisoformat(match.group(2)))
                continue
            bars = self._load_file(csv_path)
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)
        if not starts or not ends:
            return None, None
        return min(starts), max(ends)

    def has_required_timeframes(self, symbol: str, required_timeframes: list[TF]) -> bool:
        for tf in required_timeframes:
            if self._find_csv_file(symbol, tf) is None:
                return False
        return True
