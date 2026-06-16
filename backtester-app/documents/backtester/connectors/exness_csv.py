"""
Local Exness structured CSV history reader.
Reads OHLCV from disk — no HTTP/MT5.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes

TF_FOLDER_MAP: dict[TF, str] = {
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

FOLDER_TF_MAP: dict[str, TF] = {v: k for k, v in TF_FOLDER_MAP.items()}

DEFAULT_WINDOWS_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"

_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


def resolve_data_root(cli_root: str | None = None) -> Optional[Path]:
    """Resolve history root: CLI > env > Windows default."""
    if cli_root:
        path = Path(cli_root)
        if path.is_dir():
            return path

    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_folders(path):
            return path

    default = Path(DEFAULT_WINDOWS_ROOT)
    if default.is_dir() and _has_symbol_folders(default):
        return default

    return None


def _has_symbol_folders(root: Path) -> bool:
    try:
        for child in root.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                return True
    except OSError:
        return False
    return False


class ExnessCSVClient:
    """Reads local Exness CSV history from structured folders."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF], list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        symbols = sorted(
            d.name
            for d in self.data_root.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
        return symbols

    def get_available_timeframes(self, symbol: str) -> list[TF]:
        sym_dir = self.data_root / symbol.upper()
        if not sym_dir.is_dir():
            return []
        tfs: list[TF] = []
        for tf_dir in sym_dir.iterdir():
            if tf_dir.is_dir() and tf_dir.name in FOLDER_TF_MAP:
                if any(tf_dir.glob("*.csv")):
                    tfs.append(FOLDER_TF_MAP[tf_dir.name])
        return sorted(tfs, key=lambda t: tf_to_minutes(t))

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder = TF_FOLDER_MAP.get(timeframe)
        if not folder:
            return None
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return None
        files = sorted(tf_dir.glob("*.csv"))
        return files[0] if files else None

    def get_full_date_range(
        self, symbol: str, required_timeframes: list[TF]
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            csv_path = self._find_csv_file(symbol, tf)
            if not csv_path:
                continue
            start, end = self._parse_filename_dates(csv_path)
            if start and end:
                starts.append(start)
                ends.append(end)
                continue
            bars = self._load_csv(csv_path)
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)
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
        cache_key = (symbol.upper(), timeframe)
        if cache_key not in self._cache:
            csv_path = self._find_csv_file(symbol, timeframe)
            if not csv_path:
                self._cache[cache_key] = []
            else:
                self._cache[cache_key] = self._load_csv(csv_path)

        all_bars = self._cache[cache_key]
        if not all_bars:
            return []

        start_naive = _to_naive_utc(start)
        end_naive = _to_naive_utc(end)
        return [b for b in all_bars if start_naive <= _to_naive_utc(b.time) <= end_naive]

    def _parse_filename_dates(self, path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = _FILENAME_RE.match(path.name)
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

    def _load_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            import csv

            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    bar = self._row_to_bar(row)
                    if bar:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSV] Failed to read {path}: {exc}")
            return []

        bars.sort(key=lambda b: b.time)
        return bars

    def _row_to_bar(self, row: dict) -> Optional[Bar]:
        time_str = row.get("time_utc") or row.get("time")
        if not time_str:
            return None
        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
        except ValueError:
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


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
