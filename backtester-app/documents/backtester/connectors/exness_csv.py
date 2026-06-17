"""
Local Exness structured CSV history reader.
Reads OHLCV from: {data_root}/{SYMBOL}/{tf_folder}/*.csv
"""

from __future__ import annotations

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
    r"(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads local Exness structured CSV history."""

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
            bars = self.get_bars(symbol, tf)
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
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._load_symbol_tf(symbol, timeframe)

        bars = self._cache[cache_key]
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
        tf_folder = TF_TO_FOLDER.get(timeframe)
        if tf_folder is None:
            return []

        sym_dir = self.data_root / symbol.upper() / tf_folder
        if not sym_dir.is_dir():
            return []

        csv_files = sorted(sym_dir.glob("*.csv"))
        if not csv_files:
            return []

        all_bars: list[Bar] = []
        for csv_path in csv_files:
            all_bars.extend(self._parse_csv(csv_path))

        all_bars.sort(key=lambda b: b.time)
        deduped: list[Bar] = []
        seen: set[datetime] = set()
        for bar in all_bars:
            if bar.time in seen:
                continue
            seen.add(bar.time)
            deduped.append(bar)
        return deduped

    def _parse_csv(self, csv_path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(csv_path, "r", encoding="utf-8") as handle:
                header = handle.readline().strip().lower()
                if not header:
                    return []
                cols = [c.strip() for c in header.split(",")]
                time_idx = self._col_index(cols, ("time_utc", "time"))
                if time_idx is None:
                    return []

                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(",")
                    if len(parts) <= time_idx:
                        continue
                    dt = self._parse_time(parts[time_idx])
                    if dt is None:
                        continue
                    try:
                        bars.append(
                            Bar(
                                time=dt,
                                open=float(parts[cols.index("open")]),
                                high=float(parts[cols.index("high")]),
                                low=float(parts[cols.index("low")]),
                                close=float(parts[cols.index("close")]),
                                tick_volume=int(float(parts[cols.index("tick_volume")])),
                                spread=int(float(parts[cols.index("spread")])) if "spread" in cols else 0,
                            )
                        )
                    except (ValueError, IndexError):
                        continue
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed reading {csv_path}: {exc}")
        return bars

    @staticmethod
    def _col_index(cols: list[str], candidates: tuple[str, ...]) -> Optional[int]:
        for name in candidates:
            if name in cols:
                return cols.index(name)
        return None

    @staticmethod
    def _parse_time(raw: str) -> Optional[datetime]:
        raw = raw.strip()
        if not raw:
            return None
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            return None

    @staticmethod
    def parse_filename_dates(path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = DATE_RANGE_RE.match(path.name)
        if not match:
            return None, None
        try:
            start = datetime.strptime(match.group("start"), "%Y-%m-%d")
            end = datetime.strptime(match.group("end"), "%Y-%m-%d")
            return start, end
        except ValueError:
            return None, None
