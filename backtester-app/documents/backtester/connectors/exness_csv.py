"""
Exness CSV Client — reads local structured OHLCV history from disk.
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

FILENAME_DATE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$")


class ExnessCSVClient:
    """Local Exness structured-history CSV reader."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self._cache: dict[tuple[str, TF], list[Bar]] = {}

    def get_symbols(self) -> list[str]:
        if not self.data_root.exists():
            return []
        symbols = []
        for entry in sorted(self.data_root.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                symbols.append(entry.name.upper())
        return symbols

    def _find_csv_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        sym = symbol.upper()
        tf_folder = TF_TO_FOLDER.get(timeframe)
        if not tf_folder:
            return None

        sym_dir = self.data_root / sym
        if not sym_dir.exists():
            sym_dir = self.data_root / sym.lower()
        if not sym_dir.exists():
            return None

        tf_dir = sym_dir / tf_folder
        if tf_dir.exists():
            files = sorted(tf_dir.glob("*.csv"))
            if files:
                return files[0]

        flat = sym_dir / f"{sym}_{tf_folder}.csv"
        if flat.exists():
            return flat

        for candidate in sym_dir.glob(f"{sym}_*.csv"):
            if tf_folder in candidate.name:
                return candidate

        return None

    def _parse_timestamp(self, row: dict) -> Optional[datetime]:
        for key in ("time_utc", "time"):
            raw = row.get(key, "").strip()
            if not raw:
                continue
            try:
                if raw.endswith("Z"):
                    raw = raw[:-1] + "+00:00"
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None

    def _load_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ts = self._parse_timestamp(row)
                if ts is None:
                    continue
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
        bars.sort(key=lambda b: b.time)
        return bars

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        cache_key = (symbol.upper(), timeframe)
        if cache_key not in self._cache:
            csv_path = self._find_csv_file(symbol, timeframe)
            if csv_path is None:
                self._cache[cache_key] = []
            else:
                self._cache[cache_key] = self._load_csv(csv_path)

        all_bars = self._cache[cache_key]
        if not all_bars:
            return []

        start_aware = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        end_aware = end if end.tzinfo else end.replace(tzinfo=timezone.utc)

        return [b for b in all_bars if start_aware <= b.time <= end_aware]

    def get_full_date_range(
        self,
        symbol: str,
        required_timeframes: list[TF],
    ) -> tuple[Optional[datetime], Optional[datetime], list[str]]:
        """Return (start, end, missing_timeframes) for a symbol."""
        missing: list[str] = []
        starts: list[datetime] = []
        ends: list[datetime] = []

        for tf in required_timeframes:
            csv_path = self._find_csv_file(symbol, tf)
            if csv_path is None:
                missing.append(TF_TO_FOLDER.get(tf, str(tf)))
                continue

            cache_key = (symbol.upper(), tf)
            if cache_key not in self._cache:
                self._cache[cache_key] = self._load_csv(csv_path)

            bars = self._cache[cache_key]
            if not bars:
                missing.append(TF_TO_FOLDER.get(tf, str(tf)))
                continue

            starts.append(bars[0].time)
            ends.append(bars[-1].time)

            match = FILENAME_DATE_RE.search(csv_path.name)
            if match:
                try:
                    fn_start = datetime.fromisoformat(match.group(1)).replace(
                        tzinfo=timezone.utc
                    )
                    fn_end = datetime.fromisoformat(match.group(2)).replace(
                        tzinfo=timezone.utc
                    )
                    starts.append(fn_start)
                    ends.append(fn_end)
                except ValueError:
                    pass

        if missing:
            return None, None, missing

        return min(starts), max(ends), []

    def has_required_timeframes(self, symbol: str, required_timeframes: list[TF]) -> bool:
        _, _, missing = self.get_full_date_range(symbol, required_timeframes)
        return len(missing) == 0
