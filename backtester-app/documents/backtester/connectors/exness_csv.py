"""
Local Exness structured CSV history reader.
Reads OHLCV from: {data_root}/{SYMBOL}/{tf_folder}/{SYMBOL}_{tf}_{start}_{end}.csv
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes

FOLDER_TO_TF: dict[str, TF] = {
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

TF_TO_FOLDER: dict[TF, str] = {v: k for k, v in FOLDER_TO_TF.items()}

_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


def _parse_timestamp(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class ExnessCSVClient:
    """Reads local Exness CSV history — no HTTP or MT5."""

    def __init__(self, data_root: str):
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

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder_name = TF_TO_FOLDER.get(timeframe)
        if not folder_name:
            return None
        tf_dir = self.data_root / symbol.upper() / folder_name
        if not tf_dir.is_dir():
            return None
        candidates = sorted(tf_dir.glob(f"{symbol.upper()}_*.csv"))
        return candidates[0] if candidates else None

    def _parse_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    ts = row.get("time_utc") or row.get("time")
                    if not ts:
                        continue
                    bars.append(
                        Bar(
                            time=_parse_timestamp(ts),
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
        cache_key = (symbol.upper(), timeframe)
        if cache_key not in self._cache:
            csv_path = self._find_csv_file(symbol, timeframe)
            if csv_path is None:
                self._cache[cache_key] = []
            else:
                self._cache[cache_key] = self._parse_csv(csv_path)

        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        return [b for b in self._cache[cache_key] if start <= b.time <= end]

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        sym = symbol.upper()

        for tf in required_timeframes:
            csv_path = self._find_csv_file(sym, tf)
            if csv_path is None:
                continue

            match = _FILENAME_RE.match(csv_path.name)
            if match:
                starts.append(
                    datetime.strptime(match.group("start"), "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                )
                ends.append(
                    datetime.strptime(match.group("end"), "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                )
                continue

            bars = self._parse_csv(csv_path)
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)

        if not starts:
            return None, None
        return min(starts), max(ends)

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        return self._find_csv_file(symbol, timeframe) is not None

    def clear_cache(self) -> None:
        self._cache.clear()
