"""
Local Exness structured CSV history reader.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

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
        symbols = [
            p.name
            for p in self.data_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ]
        return sorted(symbols)

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[datetime | None, datetime | None]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            file_path = self._find_csv_file(symbol, tf)
            if file_path is None:
                continue
            start, end = self._parse_filename_dates(file_path)
            if start and end:
                starts.append(start)
                ends.append(end)
                continue
            bars = self._load_file(file_path)
            if bars:
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
            file_path = self._find_csv_file(symbol, timeframe)
            if file_path is None:
                self._cache[cache_key] = []
            else:
                self._cache[cache_key] = self._load_file(file_path)

        all_bars = self._cache[cache_key]
        if not all_bars:
            return []

        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        return [b for b in all_bars if start_utc <= b.time <= end_utc]

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        return self._find_csv_file(symbol, timeframe) is not None

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Path | None:
        folder = TF_TO_FOLDER.get(timeframe)
        if folder is None:
            return None
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return None
        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return None
        return csv_files[0]

    def _parse_filename_dates(self, file_path: Path) -> tuple[datetime | None, datetime | None]:
        match = _FILENAME_RE.match(file_path.name)
        if not match:
            return None, None
        start = datetime.strptime(match.group("start"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(match.group("end"), "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
        return start, end

    def _load_file(self, file_path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                header = handle.readline().strip().lower()
                if "time_utc" not in header:
                    return []
                for line in handle:
                    parts = line.strip().split(",")
                    if len(parts) < 8:
                        continue
                    try:
                        dt = _parse_timestamp(parts[0])
                        bars.append(
                            Bar(
                                time=dt,
                                open=float(parts[4]),
                                high=float(parts[5]),
                                low=float(parts[6]),
                                close=float(parts[7]),
                                tick_volume=int(float(parts[8])) if len(parts) > 8 else 0,
                                spread=int(float(parts[9])) if len(parts) > 9 else 0,
                            )
                        )
                    except (ValueError, IndexError):
                        continue
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed to read {file_path}: {exc}")
            return []
        bars.sort(key=lambda b: b.time)
        return bars


def _parse_timestamp(raw: str) -> datetime:
    raw = raw.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    return _ensure_utc(dt)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
