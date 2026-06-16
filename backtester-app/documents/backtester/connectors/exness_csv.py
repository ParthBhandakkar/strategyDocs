"""
Exness structured CSV history reader.
Reads OHLCV from local folder layout: {root}/{SYMBOL}/{tf_folder}/*.csv
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import csv

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes

# Exness folder name -> TF enum
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

DATE_RANGE_RE = re.compile(
    r"(?P<symbol>[A-Za-z0-9]+)_(?P<tf>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


def resolve_data_root(cli_root: str | None = None) -> Optional[Path]:
    """Resolve history root: CLI > env > Windows production default."""
    candidates: list[str] = []
    if cli_root:
        candidates.append(cli_root)
    env_path = os.getenv("LOCAL_HISTORY_PATH", "")
    if env_path:
        candidates.append(env_path)
    candidates.append(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history")

    for path_str in candidates:
        path = Path(path_str)
        if path.is_dir():
            symbol_dirs = [d for d in path.iterdir() if d.is_dir()]
            if symbol_dirs:
                return path
    return None


class ExnessCSVClient:
    """Local CSV data client with in-memory caching."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF], list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        if not self.data_root.is_dir():
            return []
        return sorted(
            d.name
            for d in self.data_root.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            bars = self.get_bars(symbol, tf)
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)
        if not starts or not ends:
            return None, None
        return max(starts), min(ends)

    def has_timeframes(self, symbol: str, required_timeframes: list[TF]) -> bool:
        for tf in required_timeframes:
            folder = TF_TO_FOLDER.get(tf)
            if not folder:
                return False
            tf_dir = self.data_root / symbol / folder
            if not tf_dir.is_dir() or not list(tf_dir.glob("*.csv")):
                return False
        return True

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._load_symbol_tf(symbol, timeframe)

        bars = self._cache[cache_key]
        if not bars:
            return []

        if start is None and end is None:
            return list(bars)

        filtered: list[Bar] = []
        for bar in bars:
            if start and bar.time < start:
                continue
            if end and bar.time > end:
                continue
            filtered.append(bar)
        return filtered

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return []

        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return []

        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return []

        all_bars: list[Bar] = []
        for csv_file in csv_files:
            all_bars.extend(self._parse_csv(csv_file))

        all_bars.sort(key=lambda b: b.time)
        # Deduplicate by timestamp
        deduped: list[Bar] = []
        seen: set[datetime] = set()
        for bar in all_bars:
            if bar.time not in seen:
                seen.add(bar.time)
                deduped.append(bar)
        return deduped

    def _parse_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    bar = self._row_to_bar(row)
                    if bar:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed reading {path}: {exc}")
        return bars

    def _row_to_bar(self, row: dict[str, str]) -> Bar | None:
        time_raw = row.get("time_utc") or row.get("time")
        if not time_raw:
            return None
        try:
            dt = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
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
