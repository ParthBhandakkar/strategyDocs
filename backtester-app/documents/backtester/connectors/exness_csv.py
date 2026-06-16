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

FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


def resolve_data_root(cli_path: str | None = None) -> Optional[Path]:
    """Resolve history root: CLI > env > Windows default."""
    candidates: list[Path] = []
    if cli_path:
        candidates.append(Path(cli_path))
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"))

    for path in candidates:
        if path.is_dir() and any(path.iterdir()):
            return path
    return None


class ExnessCSVClient:
    """Reads OHLCV from local Exness structured CSV history folders."""

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

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return False
        tf_dir = self.data_root / symbol / folder
        return tf_dir.is_dir() and any(tf_dir.glob("*.csv"))

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
        if not starts or not ends:
            return None, None
        return max(starts), min(ends)

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

        start_naive = _to_utc(start)
        end_naive = _to_utc(end)
        return [b for b in bars if start_naive <= _to_utc(b.time) <= end_naive]

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return []

        tf_dir = self.data_root / symbol / folder
        if not tf_dir.is_dir():
            return []

        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return []

        all_bars: list[Bar] = []
        for csv_file in csv_files:
            all_bars.extend(self._parse_csv(csv_file))

        all_bars.sort(key=lambda b: b.time)
        deduped: list[Bar] = []
        seen: set[datetime] = set()
        for bar in all_bars:
            key = _to_utc(bar.time)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(bar)
        return deduped

    def _parse_csv(self, path: Path) -> list[Bar]:
        import csv

        bars: list[Bar] = []
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                bar = _row_to_bar(row)
                if bar:
                    bars.append(bar)
        return bars


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


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
