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

TF_FOLDER: dict[TF, str] = {
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

FOLDER_TF: dict[str, TF] = {folder: tf for tf, folder in TF_FOLDER.items()}

_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV bars from local Exness structured history CSV files."""

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

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe)
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
        return max(starts), min(ends)

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        folder = TF_FOLDER.get(timeframe)
        if not folder:
            return False
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return False
        return any(tf_dir.glob("*.csv"))

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        folder = TF_FOLDER.get(timeframe)
        if not folder:
            return []
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return []
        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return []
        bars: list[Bar] = []
        for csv_path in csv_files:
            bars.extend(self._read_csv(csv_path))
        bars.sort(key=lambda b: b.time)
        return _dedupe_bars(bars)

    def _read_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    bar = _row_to_bar(row)
                    if bar is not None:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed reading {path}: {exc}")
        return bars


def _row_to_bar(row: dict[str, str]) -> Optional[Bar]:
    time_raw = row.get("time_utc") or row.get("time")
    if not time_raw:
        return None
    try:
        dt = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
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


def _dedupe_bars(bars: list[Bar]) -> list[Bar]:
    seen: set[datetime] = set()
    unique: list[Bar] = []
    for bar in bars:
        if bar.time in seen:
            continue
        seen.add(bar.time)
        unique.append(bar)
    return unique


def resolve_data_root(cli_arg: str | None = None) -> Optional[Path]:
    """Resolve history root: CLI > env > Windows default."""
    import os

    if cli_arg:
        path = Path(cli_arg)
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
    for entry in root.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            for tf_folder in ("1m", "1h", "5m", "15m"):
                if (entry / tf_folder).is_dir() and any((entry / tf_folder).glob("*.csv")):
                    return True
    return False
