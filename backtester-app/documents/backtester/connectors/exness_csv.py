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

FOLDER_TO_TF: dict[str, TF] = {v: k for k, v in TF_TO_FOLDER.items()}

_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV from local Exness structured history folders."""

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
            bars = self._load_symbol_tf(symbol, tf)
            if not bars:
                continue
            starts.append(bars[0].time)
            ends.append(bars[-1].time)
            file_range = self._file_date_range(symbol, tf)
            if file_range[0]:
                starts.append(file_range[0])
            if file_range[1]:
                ends.append(file_range[1])
        if not starts or not ends:
            return None, None
        return min(starts), max(ends)

    def has_timeframes(self, symbol: str, required_timeframes: list[TF]) -> bool:
        for tf in required_timeframes:
            tf_dir = self._tf_dir(symbol, tf)
            if tf_dir is None or not any(tf_dir.glob("*.csv")):
                return False
        return True

    def _tf_dir(self, symbol: str, timeframe: TF) -> Optional[Path]:
        folder = TF_TO_FOLDER.get(timeframe)
        if not folder:
            return None
        path = self.data_root / symbol.upper() / folder
        return path if path.is_dir() else None

    def _file_date_range(self, symbol: str, timeframe: TF) -> tuple[Optional[datetime], Optional[datetime]]:
        tf_dir = self._tf_dir(symbol, timeframe)
        if tf_dir is None:
            return None, None
        starts: list[datetime] = []
        ends: list[datetime] = []
        for csv_file in tf_dir.glob("*.csv"):
            match = _FILENAME_RE.match(csv_file.name)
            if not match:
                continue
            starts.append(datetime.fromisoformat(match.group("start")).replace(tzinfo=timezone.utc))
            ends.append(datetime.fromisoformat(match.group("end")).replace(tzinfo=timezone.utc))
        if not starts:
            return None, None
        return min(starts), max(ends)

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        tf_dir = self._tf_dir(symbol, timeframe)
        if tf_dir is None:
            return []
        bars: list[Bar] = []
        for csv_file in sorted(tf_dir.glob("*.csv")):
            bars.extend(self._parse_csv(csv_file))
        bars.sort(key=lambda b: b.time)
        deduped: list[Bar] = []
        seen: set[datetime] = set()
        for bar in bars:
            key = _to_naive_utc(bar.time)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(bar)
        return deduped

    def _parse_csv(self, csv_file: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with csv_file.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    ts_raw = row.get("time_utc") or row.get("time")
                    if not ts_raw:
                        continue
                    dt = _parse_timestamp(ts_raw)
                    if dt is None:
                        continue
                    bars.append(
                        Bar(
                            time=dt,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            tick_volume=int(float(row.get("tick_volume") or row.get("real_volume") or 0)),
                            spread=int(float(row.get("spread") or 0)),
                        )
                    )
        except (OSError, ValueError, KeyError) as exc:
            print(f"[ExnessCSVClient] Failed to parse {csv_file}: {exc}")
        return bars


def _parse_timestamp(value: str) -> Optional[datetime]:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def resolve_data_root(cli_path: str | None = None) -> Optional[Path]:
    """Resolve history root: CLI > env > Windows default."""
    import os

    candidates: list[Path] = []
    if cli_path:
        candidates.append(Path(cli_path))
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"))

    for candidate in candidates:
        if candidate.is_dir() and _has_symbol_folders(candidate):
            return candidate
    return None


def _has_symbol_folders(path: Path) -> bool:
    return any(p.is_dir() and not p.name.startswith(".") for p in path.iterdir())
