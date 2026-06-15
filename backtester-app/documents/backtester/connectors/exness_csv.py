"""
Local Exness structured CSV history reader.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes

# Folder name on disk -> TF enum
FOLDER_TO_TF: dict[str, TF] = {
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

TF_TO_FOLDER: dict[TF, str] = {v: k for k, v in FOLDER_TO_TF.items()}

DEFAULT_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"

_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_(?P<tf>[a-z0-9]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$"
)


def resolve_data_root(cli_root: str | None = None) -> Path | None:
    """Resolve history root: CLI > env > Windows default."""
    candidates: list[str] = []
    if cli_root:
        candidates.append(cli_root)
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        candidates.append(env_path)
    candidates.append(DEFAULT_DATA_ROOT)

    for path_str in candidates:
        path = Path(path_str)
        if path.is_dir() and any(path.iterdir()):
            return path
    return None


class ExnessCSVClient:
    """Reads OHLCV from local Exness structured CSV history."""

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

    def _find_csv(self, symbol: str, timeframe: TF) -> Path | None:
        tf_folder = TF_TO_FOLDER.get(timeframe)
        if not tf_folder:
            return None
        tf_dir = self.data_root / symbol.upper() / tf_folder
        if not tf_dir.is_dir():
            return None
        csvs = sorted(tf_dir.glob(f"{symbol.upper()}_*.csv"))
        return csvs[0] if csvs else None

    def _parse_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with open(path, newline="", encoding="utf-8") as f:
            header = f.readline()
            if not header:
                return []
            cols = [c.strip() for c in header.split(",")]
            time_idx = cols.index("time_utc") if "time_utc" in cols else cols.index("time")

            for line in f:
                parts = line.strip().split(",")
                if len(parts) <= time_idx:
                    continue
                try:
                    t_raw = parts[time_idx].strip()
                    if t_raw.endswith("Z"):
                        t_raw = t_raw[:-1] + "+00:00"
                    dt = datetime.fromisoformat(t_raw)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)

                    def col(name: str, fallback: int) -> str:
                        return parts[cols.index(name)] if name in cols else parts[fallback]

                    bars.append(
                        Bar(
                            time=dt,
                            open=float(col("open", 4)),
                            high=float(col("high", 5)),
                            low=float(col("low", 6)),
                            close=float(col("close", 7)),
                            tick_volume=int(float(col("tick_volume", 8))),
                            spread=int(float(col("spread", 9))) if "spread" in cols else 0,
                        )
                    )
                except (ValueError, IndexError):
                    continue
        bars.sort(key=lambda b: b.time)
        return bars

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        key = (symbol.upper(), timeframe)
        if key not in self._cache:
            csv_path = self._find_csv(symbol, timeframe)
            if csv_path is None:
                self._cache[key] = []
            else:
                self._cache[key] = self._parse_csv(csv_path)

        all_bars = self._cache[key]
        if not all_bars:
            return []

        start_aware = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        end_aware = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        return [b for b in all_bars if start_aware <= b.time <= end_aware]

    def get_full_date_range(
        self, symbol: str, required_timeframes: list[TF]
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        """Return intersection-friendly full range from available CSV files."""
        starts: list[datetime] = []
        ends: list[datetime] = []
        sym = symbol.upper()

        for tf in required_timeframes:
            csv_path = self._find_csv(sym, tf)
            if csv_path is None:
                continue
            m = _FILENAME_RE.match(csv_path.name)
            if m:
                starts.append(datetime.fromisoformat(m.group("start")).replace(tzinfo=timezone.utc))
                ends.append(datetime.fromisoformat(m.group("end")).replace(tzinfo=timezone.utc))
                continue
            bars = self._parse_csv(csv_path)
            if bars:
                starts.append(bars[0].time)
                ends.append(bars[-1].time)

        if not starts or not ends:
            return None, None
        return max(starts), min(ends)

    def has_timeframes(self, symbol: str, required_timeframes: list[TF]) -> bool:
        for tf in required_timeframes:
            if self._find_csv(symbol, tf) is None:
                return False
        return True
