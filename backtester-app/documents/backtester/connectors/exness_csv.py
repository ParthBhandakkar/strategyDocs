"""
Local Exness structured CSV history reader.
"""

from __future__ import annotations

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

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        folder = TF_FOLDER_MAP.get(timeframe)
        if not folder:
            return False
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return False
        return any(tf_dir.glob("*.csv"))

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            bars = self._load_symbol_tf(symbol, tf)
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
        all_bars = self._load_symbol_tf(symbol, timeframe)
        if not all_bars:
            return []
        return [b for b in all_bars if start <= b.time <= end]

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        key = (symbol.upper(), timeframe)
        if key in self._cache:
            return self._cache[key]

        folder = TF_FOLDER_MAP.get(timeframe)
        if not folder:
            self._cache[key] = []
            return []

        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            self._cache[key] = []
            return []

        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            self._cache[key] = []
            return []

        bars: list[Bar] = []
        for csv_path in csv_files:
            bars.extend(self._parse_csv(csv_path))

        bars.sort(key=lambda b: b.time)
        deduped: list[Bar] = []
        seen: set[datetime] = set()
        for bar in bars:
            if bar.time not in seen:
                seen.add(bar.time)
                deduped.append(bar)

        self._cache[key] = deduped
        return deduped

    def _parse_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                header = handle.readline()
                if not header:
                    return []
                cols = [c.strip().lower() for c in header.split(",")]
                time_idx = self._col_index(cols, ["time_utc", "time"])
                if time_idx is None:
                    return []

                for line in handle:
                    parts = line.strip().split(",")
                    if len(parts) <= time_idx:
                        continue
                    try:
                        ts = self._parse_time(parts[time_idx])
                        bars.append(
                            Bar(
                                time=ts,
                                open=float(parts[cols.index("open")]),
                                high=float(parts[cols.index("high")]),
                                low=float(parts[cols.index("low")]),
                                close=float(parts[cols.index("close")]),
                                tick_volume=int(
                                    float(parts[cols.index("tick_volume")])
                                )
                                if "tick_volume" in cols
                                else 0,
                                spread=int(float(parts[cols.index("spread")]))
                                if "spread" in cols
                                else 0,
                            )
                        )
                    except (ValueError, IndexError):
                        continue
        except OSError as exc:
            print(f"[ExnessCSVClient] Failed reading {path}: {exc}")
        return bars

    @staticmethod
    def _col_index(cols: list[str], candidates: list[str]) -> Optional[int]:
        for name in candidates:
            if name in cols:
                return cols.index(name)
        return None

    @staticmethod
    def _parse_time(value: str) -> datetime:
        value = value.strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def parse_filename_dates(path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        match = DATE_RANGE_RE.search(path.name)
        if not match:
            return None, None
        start = datetime.strptime(match.group(1), "%Y-%m-%d")
        end = datetime.strptime(match.group(2), "%Y-%m-%d")
        return start, end
