"""
Local Exness structured CSV history reader.
Reads OHLCV from: {data_root}/{SYMBOL}/{tf_folder}/*.csv
"""

from __future__ import annotations

import csv
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

DATE_RANGE_RE = re.compile(
    r"(?P<symbol>[A-Z0-9]+)_(?P<tf>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads local Exness structured CSV history (no HTTP / MT5)."""

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

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            s, e = self._file_date_range(symbol, tf)
            if s and e:
                starts.append(s)
                ends.append(e)
        if not starts:
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
            self._cache[cache_key] = self._load_symbol_tf(symbol, timeframe)

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

        bars: list[Bar] = []
        for csv_path in csv_files:
            bars.extend(self._parse_csv(csv_path))

        bars.sort(key=lambda b: b.time)
        return _dedupe_bars(bars)

    def _parse_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with path.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    bar = _row_to_bar(row)
                    if bar:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed reading {path}: {exc}")
        return bars

    def _file_date_range(
        self, symbol: str, timeframe: TF
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return None, None
        tf_dir = self.data_root / symbol / folder
        if not tf_dir.is_dir():
            return None, None

        file_starts: list[datetime] = []
        file_ends: list[datetime] = []
        for csv_path in tf_dir.glob("*.csv"):
            match = DATE_RANGE_RE.match(csv_path.name)
            if match:
                file_starts.append(_parse_date(match.group("start")))
                file_ends.append(_parse_date_end(match.group("end")))
            else:
                bars = self._parse_csv(csv_path)
                if bars:
                    file_starts.append(bars[0].time)
                    file_ends.append(bars[-1].time)

        if not file_starts:
            return None, None
        return min(file_starts), max(file_ends)


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


def _parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _parse_date_end(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )


def _dedupe_bars(bars: list[Bar]) -> list[Bar]:
    seen: set[datetime] = set()
    out: list[Bar] = []
    for bar in bars:
        if bar.time in seen:
            continue
        seen.add(bar.time)
        out.append(bar)
    return out
