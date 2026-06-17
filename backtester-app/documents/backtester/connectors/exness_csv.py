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
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV from local Exness structured history folders."""

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
        start_naive = _to_utc(start)
        end_naive = _to_utc(end)
        return [b for b in bars if start_naive <= _to_utc(b.time) <= end_naive]

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        folder_name = TF_TO_FOLDER.get(timeframe)
        if not folder_name:
            return []
        tf_dir = self.data_root / symbol.upper() / folder_name
        if not tf_dir.is_dir():
            return []
        all_bars: list[Bar] = []
        for csv_path in sorted(tf_dir.glob("*.csv")):
            all_bars.extend(self._read_csv(csv_path))
        all_bars.sort(key=lambda b: b.time)
        return _dedupe_bars(all_bars)

    def _read_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    ts = row.get("time_utc") or row.get("time")
                    if not ts:
                        continue
                    dt = _parse_time(ts)
                    if dt is None:
                        continue
                    bars.append(
                        Bar(
                            time=dt,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            tick_volume=int(float(row.get("tick_volume") or 0)),
                            spread=int(float(row.get("spread") or 0)),
                        )
                    )
        except (OSError, ValueError, KeyError) as exc:
            print(f"[ExnessCSVClient] Error reading {path}: {exc}")
        return bars


def _parse_time(value: str) -> Optional[datetime]:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _dedupe_bars(bars: list[Bar]) -> list[Bar]:
    if not bars:
        return []
    deduped = [bars[0]]
    for bar in bars[1:]:
        if bar.time != deduped[-1].time:
            deduped.append(bar)
    return deduped
