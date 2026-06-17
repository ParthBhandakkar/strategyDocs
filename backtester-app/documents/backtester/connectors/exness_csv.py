"""
Local Exness structured CSV history reader.
Reads OHLCV from disk — no MT5 HTTP or remote data fetching.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_from_string

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

FILENAME_DATE_RE = re.compile(
    r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads local Exness structured history CSV files."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF], list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        symbols = []
        for entry in sorted(self.data_root.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                symbols.append(entry.name)
        return symbols

    def _tf_folder(self, timeframe: TF) -> Optional[str]:
        return TF_TO_FOLDER.get(timeframe)

    def _find_csv_files(self, symbol: str, timeframe: TF) -> list[Path]:
        folder_name = self._tf_folder(timeframe)
        if not folder_name:
            return []
        tf_dir = self.data_root / symbol / folder_name
        if not tf_dir.is_dir():
            return []
        return sorted(tf_dir.glob("*.csv"))

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        cache_key = (symbol, timeframe)
        if use_cache and cache_key in self._cache:
            all_bars = self._cache[cache_key]
        else:
            all_bars = self._load_all_bars(symbol, timeframe)
            if use_cache:
                self._cache[cache_key] = all_bars

        if not all_bars:
            return []

        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        return [b for b in all_bars if start_utc <= b.time <= end_utc]

    def _load_all_bars(self, symbol: str, timeframe: TF) -> list[Bar]:
        files = self._find_csv_files(symbol, timeframe)
        if not files:
            return []

        bars: list[Bar] = []
        for csv_path in files:
            bars.extend(self._parse_csv(csv_path))

        bars.sort(key=lambda b: b.time)
        return _dedupe_bars(bars)

    def _parse_csv(self, csv_path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    bar = _row_to_bar(row)
                    if bar:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed to read {csv_path}: {exc}")
        return bars

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        """Return union start/end across required timeframes for a symbol."""
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            bars = self._load_all_bars(symbol, tf)
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)
        if not starts:
            return None, None
        return min(starts), max(ends)

    def symbol_has_timeframes(self, symbol: str, required_timeframes: list[TF]) -> bool:
        for tf in required_timeframes:
            if not self._find_csv_files(symbol, tf):
                return False
        return True


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            if fmt.endswith("%z"):
                dt = datetime.strptime(value.replace("Z", "+0000"), fmt)
            else:
                dt = datetime.strptime(value.replace("Z", ""), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _row_to_bar(row: dict[str, str]) -> Optional[Bar]:
    time_raw = row.get("time_utc") or row.get("time") or ""
    dt = _parse_time(time_raw)
    if dt is None:
        return None
    try:
        return Bar(
            time=dt,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            tick_volume=int(float(row.get("tick_volume") or row.get("real_volume") or 0)),
            spread=int(float(row.get("spread") or 0)),
        )
    except (KeyError, ValueError):
        return None


def _dedupe_bars(bars: list[Bar]) -> list[Bar]:
    seen: set[datetime] = set()
    out: list[Bar] = []
    for bar in bars:
        if bar.time in seen:
            continue
        seen.add(bar.time)
        out.append(bar)
    return out


def parse_tf_from_config(values: list[str]) -> list[TF]:
    return [tf_from_string(v) for v in values]
