"""
Exness structured CSV history reader.
Reads OHLCV from local folder layout: {root}/{SYMBOL}/{tf_folder}/*.csv
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes

_DATE_RANGE_RE = re.compile(
    r"(?P<symbol>[^_]+)_(?P<tf>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Local Exness CSV data client."""

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

    def _resolve_csv_path(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder = tf_to_folder(timeframe)
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return None
        files = sorted(tf_dir.glob("*.csv"))
        return files[-1] if files else None

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        key = (symbol.upper(), timeframe)
        if key not in self._cache:
            self._cache[key] = self._load_symbol_tf(symbol, timeframe)
        bars = self._cache[key]
        if not bars:
            return []
        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        return [b for b in bars if start_utc <= b.time <= end_utc]

    def get_full_date_range(
        self, symbol: str, required_timeframes: list[TF]
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            bars = self._load_symbol_tf(symbol, tf)
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)
        if not starts:
            return None, None
        return min(starts), max(ends)

    def has_required_timeframes(self, symbol: str, required_timeframes: list[TF]) -> bool:
        for tf in required_timeframes:
            path = self._resolve_csv_path(symbol, tf)
            if path is None:
                return False
        return True

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        key = (symbol.upper(), timeframe)
        if key in self._cache:
            return self._cache[key]

        path = self._resolve_csv_path(symbol, timeframe)
        if path is None:
            self._cache[key] = []
            return []

        bars: list[Bar] = []
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    bar = _parse_row(row)
                    if bar:
                        bars.append(bar)
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed reading {path}: {exc}")
            self._cache[key] = []
            return []

        bars.sort(key=lambda b: b.time)
        self._cache[key] = bars
        return bars


def tf_to_folder(timeframe: TF) -> str:
    mapping = {
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
    return mapping.get(timeframe, "1h")


def _parse_row(row: dict[str, str]) -> Optional[Bar]:
    ts_raw = row.get("time_utc") or row.get("time")
    if not ts_raw:
        return None
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
    except ValueError:
        return None

    try:
        return Bar(
            time=ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            tick_volume=int(float(row.get("tick_volume") or row.get("volume") or 0)),
            spread=int(float(row.get("spread") or 0)),
        )
    except (KeyError, ValueError):
        return None


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_filename_dates(path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
    match = _DATE_RANGE_RE.match(path.name)
    if not match:
        return None, None
    start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )
    return start, end
