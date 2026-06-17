"""
Local Exness structured CSV history reader.
Reads OHLCV from: {data_root}/{SYMBOL}/{tf_folder}/*.csv
"""

from __future__ import annotations

import csv
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_from_string

# Folder name on disk -> TF enum
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

_DATE_RANGE_RE = re.compile(
    r"(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads local Exness structured CSV history."""

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
        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        return [b for b in bars if start_utc <= b.time <= end_utc]

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            bars = self._load_symbol_tf(symbol, tf)
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)
        if not starts:
            return None, None
        return min(starts), max(ends)

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        tf_folder = TF_TO_FOLDER.get(timeframe)
        if not tf_folder:
            return False
        sym_dir = self.data_root / symbol / tf_folder
        if not sym_dir.is_dir():
            return False
        return any(sym_dir.glob("*.csv"))

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        tf_folder = TF_TO_FOLDER.get(timeframe)
        if not tf_folder:
            return []
        sym_dir = self.data_root / symbol / tf_folder
        if not sym_dir.is_dir():
            return []
        csv_files = sorted(sym_dir.glob("*.csv"))
        if not csv_files:
            return []
        all_bars: list[Bar] = []
        for csv_path in csv_files:
            all_bars.extend(self._parse_csv(csv_path))
        all_bars.sort(key=lambda b: b.time)
        # Deduplicate by timestamp
        seen: set[datetime] = set()
        unique: list[Bar] = []
        for bar in all_bars:
            if bar.time not in seen:
                seen.add(bar.time)
                unique.append(bar)
        return unique

    def _parse_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    bar = _row_to_bar(row)
                    if bar:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSV] Failed to read {path}: {exc}")
        return bars


def resolve_data_root(cli_path: str | None = None) -> Optional[Path]:
    """Resolve history root: CLI > env > Windows default."""
    if cli_path:
        p = Path(cli_path)
        if p.is_dir() and _has_symbol_data(p):
            return p
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_dir() and _has_symbol_data(p):
            return p
    default = Path(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history")
    if default.is_dir() and _has_symbol_data(default):
        return default
    return None


def _has_symbol_data(root: Path) -> bool:
    for entry in root.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            for sub in entry.iterdir():
                if sub.is_dir() and any(sub.glob("*.csv")):
                    return True
    return False


def _row_to_bar(row: dict) -> Optional[Bar]:
    time_str = row.get("time_utc") or row.get("time")
    if not time_str:
        return None
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
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


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_filename_dates(path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
    match = _DATE_RANGE_RE.match(path.name)
    if not match:
        return None, None
    try:
        start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
        return start, end
    except ValueError:
        return None, None
