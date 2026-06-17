"""
Local Exness structured CSV history reader.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_folder, tf_from_folder


_DATE_RANGE_RE = re.compile(
    r"(?P<symbol>[A-Z0-9]+)_(?P<tf>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
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

    def _csv_path(self, symbol: str, timeframe: TF) -> Optional[Path]:
        tf_folder = self.data_root / symbol.upper() / tf_to_folder(timeframe)
        if not tf_folder.is_dir():
            return None
        csv_files = sorted(tf_folder.glob(f"{symbol.upper()}_*.csv"))
        if not csv_files:
            csv_files = sorted(tf_folder.glob("*.csv"))
        return csv_files[0] if csv_files else None

    def _parse_time(self, raw: str) -> datetime:
        raw = raw.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    def _load_csv(self, symbol: str, timeframe: TF) -> list[Bar]:
        key = (symbol.upper(), timeframe)
        if key in self._cache:
            return self._cache[key]

        path = self._csv_path(symbol, timeframe)
        if path is None:
            self._cache[key] = []
            return []

        bars: list[Bar] = []
        try:
            import csv

            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    time_raw = row.get("time_utc") or row.get("time") or ""
                    if not time_raw:
                        continue
                    bars.append(
                        Bar(
                            time=self._parse_time(time_raw),
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            tick_volume=int(float(row.get("tick_volume") or 0)),
                            spread=int(float(row.get("spread") or 0)),
                        )
                    )
        except (OSError, ValueError, KeyError) as exc:
            print(f"[ExnessCSVClient] Failed reading {path}: {exc}")
            bars = []

        bars.sort(key=lambda b: b.time)
        self._cache[key] = bars
        return bars

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        all_bars = self._load_csv(symbol, timeframe)
        if not all_bars:
            return []
        return [b for b in all_bars if start <= b.time <= end]

    def get_full_date_range(
        self, symbol: str, required_timeframes: list[TF]
    ) -> tuple[Optional[datetime], Optional[datetime], list[str]]:
        """Return (start, end, missing_timeframes) for a symbol."""
        missing: list[str] = []
        starts: list[datetime] = []
        ends: list[datetime] = []

        for tf in required_timeframes:
            bars = self._load_csv(symbol, tf)
            if not bars:
                missing.append(tf.name)
                continue
            starts.append(bars[0].time)
            ends.append(bars[-1].time)

        if missing or not starts or not ends:
            return None, None, missing

        return max(starts), min(ends), missing

    def scan_timeframes(self, symbol: str) -> list[TF]:
        sym_dir = self.data_root / symbol.upper()
        if not sym_dir.is_dir():
            return []
        found: list[TF] = []
        for sub in sym_dir.iterdir():
            if not sub.is_dir():
                continue
            try:
                found.append(tf_from_folder(sub.name))
            except ValueError:
                continue
        return found

    @staticmethod
    def parse_filename_range(path: Path) -> tuple[Optional[datetime], Optional[datetime]]:
        m = _DATE_RANGE_RE.match(path.name)
        if not m:
            return None, None
        start = datetime.strptime(m.group("start"), "%Y-%m-%d")
        end = datetime.strptime(m.group("end"), "%Y-%m-%d")
        return start, end
