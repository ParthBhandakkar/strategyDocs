"""
Local Exness OHLCV reader — loads structured history from disk when available.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes, tf_short
from backtester.connectors.synthetic import SyntheticDataClient


class LocalHistoryClient:
    """Reads OHLCV CSV files from LOCAL_HISTORY_PATH; falls back to synthetic data."""

    def __init__(self, history_path: str | None = None, fallback_seed: int = 42):
        self.history_path = Path(
            history_path or os.getenv("LOCAL_HISTORY_PATH", "")
        )
        self._synthetic = SyntheticDataClient(seed=fallback_seed)
        self._available = self.history_path.is_dir()

    def health_check(self) -> dict:
        if self._available:
            return {"status": "ok", "source": "local", "path": str(self.history_path)}
        return self._synthetic.health_check()

    def get_symbols(self) -> list[str]:
        if not self._available:
            return self._synthetic.get_symbols()
        symbols = []
        for entry in self.history_path.iterdir():
            if entry.is_dir():
                symbols.append(entry.name)
        return sorted(symbols) if symbols else self._synthetic.get_symbols()

    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> list[Bar]:
        del use_cache
        if not self._available:
            return self._synthetic.get_bars(symbol, timeframe, start, end)

        tf_label = tf_short(timeframe)
        candidates = [
            self.history_path / symbol / f"{tf_label}.csv",
            self.history_path / symbol / f"{int(timeframe)}.csv",
            self.history_path / symbol / tf_label.lower() / "ohlcv.csv",
        ]
        for path in candidates:
            if path.exists():
                bars = self._read_csv(path, start, end)
                if bars:
                    return bars

        return self._synthetic.get_bars(symbol, timeframe, start, end)

    def _read_csv(self, path: Path, start: datetime, end: datetime) -> list[Bar]:
        bars: list[Bar] = []
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    t_raw = row.get("time") or row.get("datetime") or row.get("timestamp")
                    if not t_raw:
                        continue
                    t_raw = t_raw.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(t_raw)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < start or dt > end:
                        continue
                    bars.append(
                        Bar(
                            time=dt,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            tick_volume=int(float(row.get("tick_volume") or row.get("volume") or 0)),
                            spread=int(float(row.get("spread") or 0)),
                        )
                    )
                except (KeyError, ValueError):
                    continue
        return bars

    def close(self):
        self._synthetic.close()
