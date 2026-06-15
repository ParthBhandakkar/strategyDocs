"""
Read OHLCV bars from local Exness structured history on disk.
Default path (Windows): O:\\D temp\\UltimateTradeBot\\Data\\Exness\\structured\\history
Override with LOCAL_HISTORY_PATH in the environment.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_short

DEFAULT_HISTORY_PATH = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"

_TIME_COLUMNS = ("time", "timestamp", "datetime", "date", "bar_time")
_OHLC_COLUMNS = {
    "open": ("open", "o", "Open"),
    "high": ("high", "h", "High"),
    "low": ("low", "l", "Low"),
    "close": ("close", "c", "Close"),
}
_VOLUME_COLUMNS = ("tick_volume", "volume", "vol", "tickvolume", "Volume")


class LocalHistoryClient:
    """Loads pre-downloaded OHLCV history from a local directory tree."""

    def __init__(self, history_root: str | Path | None = None):
        self.history_root = Path(
            history_root or os.getenv("LOCAL_HISTORY_PATH", DEFAULT_HISTORY_PATH)
        )
        self._bars_cache: dict[str, list[Bar]] = {}

    def health_check(self) -> dict:
        if not self.history_root.exists():
            return {
                "status": "error",
                "source": "local_history",
                "path": str(self.history_root),
                "error": "History directory not found",
            }
        symbols = self.get_symbols()
        return {
            "status": "ok",
            "source": "local_history",
            "path": str(self.history_root),
            "symbol_count": len(symbols),
        }

    def get_symbols(self) -> list[str]:
        if not self.history_root.exists():
            return []

        symbols: set[str] = set()
        for child in self.history_root.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                symbols.add(child.name.upper())

        for path in self.history_root.rglob("*"):
            if not path.is_file():
                continue
            stem = path.stem.upper()
            for part in stem.replace("-", "_").split("_"):
                if len(part) >= 6 and part.isalpha():
                    symbols.add(part)
        return sorted(symbols)

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        cache_key = f"{symbol.upper()}_{int(timeframe)}"
        if use_cache and cache_key in self._bars_cache:
            return self._filter_bars(self._bars_cache[cache_key], start, end)

        file_path = self._resolve_history_file(symbol, timeframe)
        if file_path is None:
            print(
                f"[LocalHistoryClient] No history file for {symbol} {tf_short(timeframe)} "
                f"under {self.history_root}"
            )
            return []

        bars = self._load_file(file_path)
        if use_cache:
            self._bars_cache[cache_key] = bars
        return self._filter_bars(bars, start, end)

    def close(self):
        self._bars_cache.clear()

    def _resolve_history_file(self, symbol: str, timeframe: TF) -> Optional[Path]:
        if not self.history_root.exists():
            return None

        sym = symbol.upper()
        tf = tf_short(timeframe)
        tf_lower = tf.lower()

        candidates = [
            self.history_root / sym / f"{tf}.csv",
            self.history_root / sym / f"{tf_lower}.csv",
            self.history_root / sym / f"{tf}.json",
            self.history_root / sym / f"{tf_lower}.json",
            self.history_root / sym / f"{sym}_{tf}.csv",
            self.history_root / sym / f"{sym}_{tf_lower}.csv",
            self.history_root / f"{sym}_{tf}.csv",
            self.history_root / f"{sym}_{tf_lower}.csv",
            self.history_root / sym / "ohlc" / f"{tf}.csv",
            self.history_root / sym / "ohlc" / f"{tf_lower}.csv",
            self.history_root / sym / f"ohlc_{tf}.csv",
            self.history_root / sym / f"ohlc_{tf_lower}.csv",
            self.history_root / sym / f"{tf}.parquet",
            self.history_root / sym / f"{tf_lower}.parquet",
        ]

        for path in candidates:
            if path.exists():
                return path

        # Fallback: any file under symbol folder that mentions the timeframe.
        symbol_dir = self.history_root / sym
        if symbol_dir.is_dir():
            for path in sorted(symbol_dir.rglob("*")):
                if not path.is_file():
                    continue
                name = path.name.lower()
                if tf_lower in name and path.suffix.lower() in {".csv", ".json", ".parquet"}:
                    return path

        # Last resort: search entire tree for symbol + timeframe in filename.
        for path in sorted(self.history_root.rglob("*")):
            if not path.is_file():
                continue
            stem = path.stem.upper()
            if sym in stem and tf in stem and path.suffix.lower() in {".csv", ".json", ".parquet"}:
                return path

        return None

    def _load_file(self, path: Path) -> list[Bar]:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return self._load_csv(path)
        if suffix == ".json":
            return self._load_json(path)
        if suffix == ".parquet":
            return self._load_parquet(path)
        return []

    def _load_csv(self, path: Path) -> list[Bar]:
        bars: list[Bar] = []
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                return []
            fields = {name.strip().lower(): name for name in reader.fieldnames}
            for row in reader:
                bar = self._row_to_bar(row, fields)
                if bar:
                    bars.append(bar)
        return sorted(bars, key=lambda bar: bar.time)

    def _load_json(self, path: Path) -> list[Bar]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "bars" in raw:
            raw = raw["bars"]
        if not isinstance(raw, list):
            return []
        return self._parse_bars(raw)

    def _load_parquet(self, path: Path) -> list[Bar]:
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError(
                "Parquet history files require pandas. Install pandas or export CSV/JSON."
            ) from exc

        frame = pd.read_parquet(path)
        bars: list[Bar] = []
        columns = {col.lower(): col for col in frame.columns}
        for _, row in frame.iterrows():
            mapped = {columns[key]: row[columns[key]] for key in columns}
            bar = self._row_to_bar(mapped, columns)
            if bar:
                bars.append(bar)
        return sorted(bars, key=lambda bar: bar.time)

    def _parse_bars(self, raw_bars: list[dict]) -> list[Bar]:
        bars: list[Bar] = []
        for item in raw_bars:
            fields = {key.lower(): key for key in item.keys()}
            bar = self._row_to_bar(item, fields)
            if bar:
                bars.append(bar)
        return sorted(bars, key=lambda bar: bar.time)

    def _row_to_bar(self, row: dict, fields: dict[str, str]) -> Optional[Bar]:
        time_key = self._pick_field(fields, _TIME_COLUMNS)
        if not time_key:
            return None

        raw_time = row.get(fields[time_key])
        dt = self._parse_time(raw_time)
        if dt is None:
            return None

        try:
            open_key = self._pick_field(fields, _OHLC_COLUMNS["open"])
            high_key = self._pick_field(fields, _OHLC_COLUMNS["high"])
            low_key = self._pick_field(fields, _OHLC_COLUMNS["low"])
            close_key = self._pick_field(fields, _OHLC_COLUMNS["close"])
            if not all([open_key, high_key, low_key, close_key]):
                return None

            volume_key = self._pick_field(fields, _VOLUME_COLUMNS)
            volume = 0
            if volume_key:
                volume = int(float(row.get(fields[volume_key], 0) or 0))

            return Bar(
                time=dt,
                open=float(row[fields[open_key]]),
                high=float(row[fields[high_key]]),
                low=float(row[fields[low_key]]),
                close=float(row[fields[close_key]]),
                tick_volume=volume,
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _pick_field(fields: dict[str, str], candidates: tuple[str, ...]) -> Optional[str]:
        for candidate in candidates:
            if candidate.lower() in fields:
                return candidate.lower()
        return None

    @staticmethod
    def _parse_time(value: object) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1_000_000_000_000:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)

        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    @staticmethod
    def _filter_bars(bars: list[Bar], start: datetime, end: datetime) -> list[Bar]:
        return [bar for bar in bars if start <= bar.time <= end]
