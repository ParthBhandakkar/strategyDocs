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

FILENAME_RANGE_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
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
            self._cache[cache_key] = self._load_all_bars(symbol, timeframe)
        all_bars = self._cache[cache_key]
        if not all_bars:
            return []
        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        return [b for b in all_bars if start_utc <= b.time <= end_utc]

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return False
        tf_dir = self.data_root / symbol / folder
        if not tf_dir.is_dir():
            return False
        return any(tf_dir.glob("*.csv"))

    def _load_all_bars(self, symbol: str, timeframe: TF) -> list[Bar]:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return []
        tf_dir = self.data_root / symbol / folder
        if not tf_dir.is_dir():
            return []
        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return []
        bars: list[Bar] = []
        for csv_file in csv_files:
            bars.extend(self._parse_csv(csv_file))
        bars.sort(key=lambda b: b.time)
        return _dedupe_bars(bars)

    def _parse_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(path, encoding="utf-8") as handle:
                header = handle.readline()
                if not header:
                    return []
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(",")
                    if len(parts) < 9:
                        continue
                    ts = parts[0].strip()
                    if not ts:
                        continue
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    bars.append(
                        Bar(
                            time=dt,
                            open=float(parts[4]),
                            high=float(parts[5]),
                            low=float(parts[6]),
                            close=float(parts[7]),
                            tick_volume=int(float(parts[8] or 0)),
                            spread=int(float(parts[9] or 0)) if len(parts) > 9 else 0,
                        )
                    )
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed reading {path}: {exc}")
        return bars

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
        starts: list[datetime] = []
        ends: list[datetime] = []
        for csv_file in tf_dir.glob("*.csv"):
            match = FILENAME_RANGE_RE.match(csv_file.name)
            if match:
                starts.append(_parse_date(match.group("start")))
                ends.append(_parse_date(match.group("end"), end_of_day=True))
                continue
            bars = self._parse_csv(csv_file)
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)
        if not starts or not ends:
            return None, None
        return min(starts), max(ends)


def resolve_data_root(cli_path: str | None = None) -> Optional[Path]:
    if cli_path:
        path = Path(cli_path)
        if path.is_dir() and _has_symbol_folders(path):
            return path
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_folders(path):
            return path
    default = Path(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history")
    if default.is_dir() and _has_symbol_folders(default):
        return default
    return None


def _has_symbol_folders(path: Path) -> bool:
    return any(p.is_dir() for p in path.iterdir() if not p.name.startswith("."))


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_date(value: str, end_of_day: bool = False) -> datetime:
    dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_of_day:
        return dt.replace(hour=23, minute=59, second=59)
    return dt


def _dedupe_bars(bars: list[Bar]) -> list[Bar]:
    seen: set[datetime] = set()
    unique: list[Bar] = []
    for bar in bars:
        if bar.time in seen:
            continue
        seen.add(bar.time)
        unique.append(bar)
    return unique
