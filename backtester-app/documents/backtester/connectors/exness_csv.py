"""
Local Exness structured CSV history reader.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_folder_name, tf_from_folder

_DATE_RANGE_RE = re.compile(
    r"(?P<symbol>[A-Z0-9]+)_(?P<tf>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV bars from local Exness structured history folders."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF], list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        symbols = []
        for entry in sorted(self.data_root.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                symbols.append(entry.name.upper())
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
        start_naive = _to_naive_utc(start)
        end_naive = _to_naive_utc(end)
        return [b for b in bars if start_naive <= _to_naive_utc(b.time) <= end_naive]

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
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)
        if not starts:
            return None, None
        return min(starts), max(ends)

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        folder = self.data_root / symbol.upper() / tf_folder_name(timeframe)
        if not folder.is_dir():
            return False
        return any(folder.glob("*.csv"))

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        tf_dir = self.data_root / symbol.upper() / tf_folder_name(timeframe)
        if not tf_dir.is_dir():
            return []
        all_bars: list[Bar] = []
        for csv_path in sorted(tf_dir.glob("*.csv")):
            all_bars.extend(self._parse_csv(csv_path))
        all_bars.sort(key=lambda b: b.time)
        return _dedupe_bars(all_bars)

    def _parse_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    bar = _row_to_bar(row)
                    if bar:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed reading {path}: {exc}")
        return bars


def resolve_data_root(cli_path: str | None = None) -> Optional[Path]:
    """Resolve history root: CLI > env > Windows default."""
    import os

    candidates: list[Path] = []
    if cli_path:
        candidates.append(Path(cli_path))
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(
        Path(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history")
    )
    for candidate in candidates:
        if candidate.is_dir() and _has_symbol_folders(candidate):
            return candidate
    return None


def _has_symbol_folders(root: Path) -> bool:
    for entry in root.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            return True
    return False


def _row_to_bar(row: dict[str, str]) -> Optional[Bar]:
    time_raw = row.get("time_utc") or row.get("time")
    if not time_raw:
        return None
    try:
        dt = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
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


def _dedupe_bars(bars: list[Bar]) -> list[Bar]:
    seen: set[datetime] = set()
    unique: list[Bar] = []
    for bar in bars:
        if bar.time in seen:
            continue
        seen.add(bar.time)
        unique.append(bar)
    return unique


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
