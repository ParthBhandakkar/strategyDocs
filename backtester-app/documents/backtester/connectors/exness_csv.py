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
from backtester.core.timeframes import TF, tf_short

TF_TO_FOLDER: dict[TF, str] = {
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

FOLDER_TO_TF: dict[str, TF] = {folder: tf for tf, folder in TF_TO_FOLDER.items()}

FILENAME_RANGE_RE = re.compile(
    r"_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV from local Exness structured history CSV files."""

    def __init__(self, data_root: str):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF], list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        symbols = [
            path.name
            for path in self.data_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
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
            bars = self.get_bars(
                symbol,
                tf,
                datetime(1970, 1, 1, tzinfo=timezone.utc),
                datetime(2099, 12, 31, tzinfo=timezone.utc),
            )
            if not bars:
                continue
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
            self._cache[cache_key] = self._load_symbol_timeframe(symbol, timeframe)
        bars = self._cache[cache_key]
        if not bars:
            return []
        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        return [bar for bar in bars if start_utc <= _ensure_utc(bar.time) <= end_utc]

    def _load_symbol_timeframe(self, symbol: str, timeframe: TF) -> list[Bar]:
        tf_folder = TF_TO_FOLDER.get(timeframe)
        if not tf_folder:
            return []
        folder = self.data_root / symbol.upper() / tf_folder
        if not folder.is_dir():
            return []
        csv_files = sorted(folder.glob("*.csv"))
        if not csv_files:
            return []
        bars: list[Bar] = []
        for csv_path in csv_files:
            bars.extend(self._read_csv_file(csv_path))
        bars.sort(key=lambda bar: bar.time)
        deduped: dict[datetime, Bar] = {}
        for bar in bars:
            deduped[_ensure_utc(bar.time)] = bar
        return [deduped[key] for key in sorted(deduped)]

    def _read_csv_file(self, csv_path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with csv_path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    bar = _parse_row(row)
                    if bar is not None:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed to read {csv_path}: {exc}")
        return bars

    def list_available_timeframes(self, symbol: str) -> list[TF]:
        symbol_dir = self.data_root / symbol.upper()
        if not symbol_dir.is_dir():
            return []
        available: list[TF] = []
        for child in symbol_dir.iterdir():
            if child.is_dir() and child.name in FOLDER_TO_TF and any(child.glob("*.csv")):
                available.append(FOLDER_TO_TF[child.name])
        return available


def _parse_row(row: dict[str, str]) -> Optional[Bar]:
    time_raw = row.get("time_utc") or row.get("time")
    if not time_raw:
        return None
    try:
        timestamp = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    try:
        return Bar(
            time=timestamp,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            tick_volume=int(float(row.get("tick_volume") or 0)),
            spread=int(float(row.get("spread") or 0)),
        )
    except (KeyError, ValueError):
        return None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def resolve_data_root(cli_path: Optional[str] = None) -> Optional[str]:
    """Resolve history root: CLI > env > Windows default."""
    import os

    candidates: list[str] = []
    if cli_path:
        candidates.append(cli_path)
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        candidates.append(env_path)
    candidates.append(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history")

    for candidate in candidates:
        root = Path(candidate)
        if root.is_dir() and _has_symbol_folders(root):
            return str(root)
    return None


def _has_symbol_folders(root: Path) -> bool:
    return any(
        child.is_dir() and not child.name.startswith(".")
        for child in root.iterdir()
    )
