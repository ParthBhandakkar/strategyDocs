"""
Local Exness structured CSV history reader.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes

TF_FOLDER: dict[TF, str] = {
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

FOLDER_TF: dict[str, TF] = {folder: tf for tf, folder in TF_FOLDER.items()}

_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


class ExnessCSVClient:
    """Reads OHLCV from local Exness structured history CSV files."""

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
    ) -> tuple[datetime | None, datetime | None]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            start, end = self._file_date_range(symbol, tf)
            if start and end:
                starts.append(start)
                ends.append(end)
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
        return [b for b in bars if start <= b.time <= end]

    def has_timeframe(self, symbol: str, timeframe: TF) -> bool:
        folder = self.data_root / symbol.upper() / TF_FOLDER.get(timeframe, "")
        if not folder.is_dir():
            return False
        return any(folder.glob("*.csv"))

    def _load_symbol_tf(self, symbol: str, timeframe: TF) -> list[Bar]:
        folder_name = TF_FOLDER.get(timeframe)
        if not folder_name:
            return []
        tf_dir = self.data_root / symbol.upper() / folder_name
        if not tf_dir.is_dir():
            return []
        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return []
        all_bars: list[Bar] = []
        for csv_path in csv_files:
            all_bars.extend(self._read_csv(csv_path))
        all_bars.sort(key=lambda b: b.time)
        return self._dedupe_bars(all_bars)

    def _read_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ts_raw = row.get("time_utc") or row.get("time")
                if not ts_raw:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
                try:
                    bars.append(
                        Bar(
                            time=ts,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            tick_volume=int(float(row.get("tick_volume") or 0)),
                            spread=int(float(row.get("spread") or 0)),
                        )
                    )
                except (KeyError, ValueError):
                    continue
        return bars

    def _file_date_range(
        self,
        symbol: str,
        timeframe: TF,
    ) -> tuple[datetime | None, datetime | None]:
        folder_name = TF_FOLDER.get(timeframe)
        if not folder_name:
            return None, None
        tf_dir = self.data_root / symbol.upper() / folder_name
        if not tf_dir.is_dir():
            return None, None
        file_starts: list[datetime] = []
        file_ends: list[datetime] = []
        for csv_path in tf_dir.glob("*.csv"):
            match = _FILENAME_RE.match(csv_path.name)
            if match:
                file_starts.append(datetime.strptime(match.group("start"), "%Y-%m-%d"))
                file_ends.append(datetime.strptime(match.group("end"), "%Y-%m-%d"))
        if file_starts:
            return min(file_starts), max(file_ends)
        bars = self._load_symbol_tf(symbol, timeframe)
        if not bars:
            return None, None
        return bars[0].time, bars[-1].time

    @staticmethod
    def _dedupe_bars(bars: list[Bar]) -> list[Bar]:
        seen: set[datetime] = set()
        unique: list[Bar] = []
        for bar in bars:
            if bar.time in seen:
                continue
            seen.add(bar.time)
            unique.append(bar)
        return unique
