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

DATE_RANGE_RE = re.compile(
    r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV from local Exness structured history CSV files."""

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

        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        return [b for b in self._cache[cache_key] if start_utc <= b.time <= end_utc]

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> Optional[tuple[datetime, datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            bars = self._load_symbol_tf(symbol, tf)
            if not bars:
                return None
            starts.append(bars[0].time)
            ends.append(bars[-1].time)
        return min(starts), max(ends)

    def has_timeframes(self, symbol: str, required_timeframes: list[TF]) -> bool:
        for tf in required_timeframes:
            folder = TF_FOLDER_MAP.get(tf)
            if not folder:
                return False
            tf_dir = self.data_root / symbol.upper() / folder
            if not tf_dir.is_dir():
                return False
            if not any(tf_dir.glob("*.csv")):
                return False
        return True

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe)
        if cache_key in self._cache:
            return self._cache[cache_key]

        folder = TF_FOLDER_MAP.get(timeframe)
        if not folder:
            self._cache[cache_key] = []
            return []

        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            self._cache[cache_key] = []
            return []

        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            self._cache[cache_key] = []
            return []

        bars: list[Bar] = []
        for csv_file in csv_files:
            bars.extend(self._parse_csv(csv_file))

        bars.sort(key=lambda b: b.time)
        deduped: list[Bar] = []
        seen: set[datetime] = set()
        for bar in bars:
            if bar.time in seen:
                continue
            seen.add(bar.time)
            deduped.append(bar)

        self._cache[cache_key] = deduped
        return deduped

    def _parse_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(path, newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    bar = _row_to_bar(row)
                    if bar:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed reading {path}: {exc}")
        return bars


def resolve_data_root(cli_path: Optional[str] = None) -> Optional[Path]:
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
    for child in root.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            for tf_folder in ("1m", "1h", "15m", "5m"):
                tf_dir = child / tf_folder
                if tf_dir.is_dir() and any(tf_dir.glob("*.csv")):
                    return True
    return False


def _row_to_bar(row: dict[str, str]) -> Optional[Bar]:
    time_raw = row.get("time_utc") or row.get("time")
    if not time_raw:
        return None
    try:
        dt = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

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
