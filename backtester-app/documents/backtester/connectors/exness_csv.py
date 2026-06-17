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

DATE_RANGE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$")


def _parse_timestamp(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class ExnessCSVClient:
    """Reads local Exness CSV history files."""

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

    def _csv_files(self, symbol: str, tf: TF) -> list[Path]:
        folder = TF_TO_FOLDER.get(tf)
        if not folder:
            return []
        tf_dir = self.data_root / symbol.upper() / folder
        if not tf_dir.is_dir():
            return []
        return sorted(tf_dir.glob("*.csv"))

    def _parse_csv_file(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                header = fh.readline()
                if not header:
                    return []
                cols = [c.strip().lower() for c in header.split(",")]
                time_idx = cols.index("time_utc") if "time_utc" in cols else cols.index("time")

                def col(name: str, fallback: int) -> int:
                    return cols.index(name) if name in cols else fallback

                oi = col("open", 4)
                hi = col("high", 5)
                li = col("low", 6)
                ci = col("close", 7)
                vi = col("tick_volume", 8)
                si = col("spread", 9)

                for line in fh:
                    parts = line.strip().split(",")
                    if len(parts) < 8:
                        continue
                    try:
                        bars.append(
                            Bar(
                                time=_parse_timestamp(parts[time_idx]),
                                open=float(parts[oi]),
                                high=float(parts[hi]),
                                low=float(parts[li]),
                                close=float(parts[ci]),
                                tick_volume=int(float(parts[vi])) if vi < len(parts) else 0,
                                spread=int(float(parts[si])) if si < len(parts) else 0,
                            )
                        )
                    except (ValueError, IndexError):
                        continue
        except OSError as exc:
            print(f"[ExnessCSV] Failed reading {path}: {exc}")
            return []
        bars.sort(key=lambda b: b.time)
        return bars

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe)
        if use_cache and cache_key in self._cache:
            all_bars = self._cache[cache_key]
        else:
            all_bars: list[Bar] = []
            for csv_path in self._csv_files(symbol, timeframe):
                all_bars.extend(self._parse_csv_file(csv_path))
            all_bars.sort(key=lambda b: b.time)
            if use_cache:
                self._cache[cache_key] = all_bars

        return [b for b in all_bars if start <= b.time <= end]

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> Optional[tuple[datetime, datetime]]:
        starts: list[datetime] = []
        ends: list[datetime] = []
        for tf in required_timeframes:
            files = self._csv_files(symbol, tf)
            if not files:
                return None
            for path in files:
                match = DATE_RANGE_RE.search(path.name)
                if match:
                    starts.append(datetime.fromisoformat(match.group(1)))
                    ends.append(datetime.fromisoformat(match.group(2)))
            bars = self.get_bars(
                symbol,
                tf,
                datetime(1970, 1, 1),
                datetime(2099, 12, 31),
            )
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)
        if not starts or not ends:
            return None
        return min(starts), max(ends)

    def has_timeframe(self, symbol: str, tf: TF) -> bool:
        return bool(self._csv_files(symbol, tf))

    @staticmethod
    def default_data_root() -> str:
        import os

        cli = os.environ.get("LOCAL_HISTORY_PATH", "")
        if cli and Path(cli).is_dir():
            symbols = [
                p
                for p in Path(cli).iterdir()
                if p.is_dir() and not p.name.startswith(".")
            ]
            if symbols:
                return cli
        return r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
