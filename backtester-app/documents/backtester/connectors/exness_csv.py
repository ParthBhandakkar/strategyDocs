"""
Local Exness structured CSV history reader.
"""

from __future__ import annotations

import os
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
        symbols = [
            p.name
            for p in self.data_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ]
        return sorted(symbols)

    def get_full_date_range(
        self, symbol: str, required_timeframes: list[TF]
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            file_range = self._file_date_range(symbol, tf)
            if file_range is None:
                continue
            starts.append(file_range[0])
            ends.append(file_range[1])
        if not starts or not ends:
            return None, None
        return min(starts), max(ends)

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe)
        if use_cache and cache_key in self._cache:
            all_bars = self._cache[cache_key]
        else:
            all_bars = self._load_symbol_timeframe(symbol, timeframe)
            if use_cache:
                self._cache[cache_key] = all_bars

        if not all_bars:
            return []

        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        return [b for b in all_bars if start_utc <= b.time <= end_utc]

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        folder = self._tf_folder(timeframe)
        sym_dir = self.data_root / symbol.upper() / folder
        if not sym_dir.is_dir():
            return False
        return any(sym_dir.glob("*.csv"))

    def _tf_folder(self, timeframe: TF) -> str:
        folder = TF_TO_FOLDER.get(timeframe)
        if folder is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        return folder

    def _file_date_range(
        self, symbol: str, timeframe: TF
    ) -> Optional[tuple[datetime, datetime]]:
        csv_path = self._find_csv_file(symbol, timeframe)
        if csv_path is None:
            return None
        match = _FILENAME_RE.match(csv_path.name)
        if match:
            start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            return start, end
        bars = self._parse_csv(csv_path)
        if not bars:
            return None
        return bars[0].time, bars[-1].time

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder = self._tf_folder(timeframe)
        sym_dir = self.data_root / symbol.upper() / folder
        if not sym_dir.is_dir():
            return None
        files = sorted(sym_dir.glob("*.csv"))
        return files[0] if files else None

    def _load_symbol_timeframe(self, symbol: str, timeframe: TF) -> list[Bar]:
        csv_path = self._find_csv_file(symbol, timeframe)
        if csv_path is None:
            return []
        bars = self._parse_csv(csv_path)
        bars.sort(key=lambda b: b.time)
        return bars

    def _parse_csv(self, csv_path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(csv_path, "r", encoding="utf-8") as handle:
                header = handle.readline().strip().lower()
                if not header:
                    return []
                columns = [c.strip() for c in header.split(",")]
                time_idx = _column_index(columns, ["time_utc", "time"])
                if time_idx is None:
                    return []
                open_idx = columns.index("open")
                high_idx = columns.index("high")
                low_idx = columns.index("low")
                close_idx = columns.index("close")
                vol_idx = _column_index(columns, ["tick_volume", "volume"])
                spread_idx = _column_index(columns, ["spread"])

                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(",")
                    if len(parts) <= close_idx:
                        continue
                    try:
                        dt = _parse_time(parts[time_idx])
                        if dt is None:
                            continue
                        bars.append(
                            Bar(
                                time=dt,
                                open=float(parts[open_idx]),
                                high=float(parts[high_idx]),
                                low=float(parts[low_idx]),
                                close=float(parts[close_idx]),
                                tick_volume=int(float(parts[vol_idx])) if vol_idx is not None else 0,
                                spread=int(float(parts[spread_idx])) if spread_idx is not None else 0,
                            )
                        )
                    except (ValueError, IndexError):
                        continue
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed to read {csv_path}: {exc}")
        return bars


def resolve_data_root(cli_path: str | None = None) -> Optional[Path]:
    """Resolve history root: CLI > env > Windows default."""
    if cli_path:
        path = Path(cli_path)
        if path.is_dir() and _has_symbol_data(path):
            return path

    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_data(path):
            return path

    default = Path(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history")
    if default.is_dir() and _has_symbol_data(default):
        return default

    return None


def _has_symbol_data(root: Path) -> bool:
    for child in root.iterdir():
        if child.is_dir() and any(child.iterdir()):
            return True
    return False


def _column_index(columns: list[str], candidates: list[str]) -> Optional[int]:
    for name in candidates:
        if name in columns:
            return columns.index(name)
    return None


def _parse_time(value: str) -> Optional[datetime]:
    value = value.strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
