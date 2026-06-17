"""
Local Exness structured CSV history reader.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

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
        self, symbol: str, required_timeframes: list[TF]
    ) -> tuple[datetime | None, datetime | None]:
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
        if not tf_folder:
            return []

        tf_dir = self.data_root / symbol.upper() / tf_folder
        if not tf_dir.is_dir():
            return []

        csv_files = sorted(tf_dir.glob("*.csv"))
        if not csv_files:
            return []

        all_bars: list[Bar] = []
        for csv_path in csv_files:
            all_bars.extend(self._parse_csv(csv_path))

        all_bars.sort(key=lambda b: b.time)
        return self._dedupe_bars(all_bars)

    def _parse_csv(self, path: Path) -> list[Bar]:
        import csv

        bars: list[Bar] = []
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    ts_raw = row.get("time_utc") or row.get("time")
                    if not ts_raw:
                        continue
                    dt = self._parse_timestamp(ts_raw)
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
            print(f"[ExnessCSVClient] Failed to parse {path}: {exc}")
        return bars

    @staticmethod
    def _parse_timestamp(value: str) -> datetime | None:
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

    @staticmethod
    def _dedupe_bars(bars: list[Bar]) -> list[Bar]:
        if not bars:
            return []
        deduped: list[Bar] = []
        seen: set[datetime] = set()
        for bar in bars:
            if bar.time in seen:
                continue
            seen.add(bar.time)
            deduped.append(bar)
        return deduped

    @staticmethod
    def tf_folder_for(timeframe: TF) -> str | None:
        return TF_TO_FOLDER.get(timeframe)

    @staticmethod
    def minutes_for(timeframe: TF) -> int:
        return tf_to_minutes(timeframe)
