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

FILENAME_DATE_RE = re.compile(
    r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$"
)


def _parse_timestamp(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


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

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder_name = next(
            (k for k, v in TF_FOLDER_MAP.items() if v == timeframe),
            None,
        )
        if folder_name is None:
            return None
        tf_dir = self.data_root / symbol / folder_name
        if not tf_dir.is_dir():
            return None
        files = sorted(tf_dir.glob(f"{symbol}_{folder_name}_*.csv"))
        return files[0] if files else None

    def _load_csv(self, symbol: str, timeframe: TF) -> list[Bar]:
        cache_key = (symbol, timeframe)
        if cache_key in self._cache:
            return self._cache[cache_key]

        csv_path = self._find_csv_file(symbol, timeframe)
        if csv_path is None:
            self._cache[cache_key] = []
            return []

        bars: list[Bar] = []
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ts_raw = row.get("time_utc") or row.get("time")
                if not ts_raw:
                    continue
                bars.append(
                    Bar(
                        time=_parse_timestamp(ts_raw),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        tick_volume=int(float(row.get("tick_volume") or 0)),
                        spread=int(float(row.get("spread") or 0)),
                    )
                )

        bars.sort(key=lambda b: b.time)
        self._cache[cache_key] = bars
        return bars

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        bars = self._load_csv(symbol, timeframe)
        if not bars:
            return []
        return [b for b in bars if start <= b.time <= end]

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            bars = self._load_csv(symbol, tf)
            if not bars:
                continue
            starts.append(bars[0].time)
            ends.append(bars[-1].time)
        if not starts or not ends:
            return None, None
        return min(starts), max(ends)

    def has_required_timeframes(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[bool, list[str]]:
        missing: list[str] = []
        for tf in required_timeframes:
            if not self._load_csv(symbol, tf):
                folder = next(
                    (k for k, v in TF_FOLDER_MAP.items() if v == tf),
                    str(tf),
                )
                missing.append(folder)
        return len(missing) == 0, missing
