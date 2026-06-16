"""
Multi-Timeframe Data Feed.
HTF bars are exposed only after bar close (anti-lookahead).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes, sort_timeframes
from backtester.core.events import MarketEvent


class BarDataClient(Protocol):
    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        ...


class MultiTimeframeDataFeed:
    """Advances time bar-by-bar on the base timeframe and emits completed bars."""

    def __init__(
        self,
        client: BarDataClient,
        symbol: str,
        timeframes: list[TF],
        start: datetime,
        end: datetime,
        extra_symbols: list[str] | None = None,
    ):
        self.client = client
        self.symbol = symbol
        self.timeframes = sort_timeframes(timeframes)
        self.base_tf = self.timeframes[0]
        self.start = start
        self.end = end
        self.extra_symbols = extra_symbols or []

        self._all_bars: dict[str, dict[TF, list[Bar]]] = defaultdict(dict)
        self._indices: dict[str, dict[TF, int]] = defaultdict(lambda: defaultdict(int))
        self._history: dict[str, dict[TF, list[Bar]]] = defaultdict(lambda: defaultdict(list))

        self._loaded = False
        self._current_time: Optional[datetime] = None

    def load(self):
        all_symbols = [self.symbol] + self.extra_symbols
        for sym in all_symbols:
            for tf in self.timeframes:
                print(f"  Loading {sym} {tf.name}...", end=" ")
                bars = self.client.get_bars(sym, tf, self.start, self.end)
                self._all_bars[sym][tf] = bars
                print(f"{len(bars)} bars")
        self._loaded = True
        base_bars = self._all_bars.get(self.symbol, {}).get(self.base_tf, [])
        if base_bars:
            self._current_time = self._bar_close_time(base_bars[0], self.base_tf)

    def __iter__(self):
        if not self._loaded:
            self.load()

        base_bars = self._all_bars.get(self.symbol, {}).get(self.base_tf, [])
        if not base_bars:
            return

        for base_bar in base_bars:
            close_time = self._bar_close_time(base_bar, self.base_tf)
            self._current_time = close_time

            new_bars: dict[TF, Bar] = {}
            multi_bars: dict[str, dict[TF, Bar]] = defaultdict(dict)

            for sym in [self.symbol] + self.extra_symbols:
                for tf in self.timeframes:
                    tf_bars = self._all_bars.get(sym, {}).get(tf, [])
                    idx = self._indices[sym][tf]

                    while idx < len(tf_bars) and self._bar_is_closed(tf_bars[idx], tf, close_time):
                        self._history[sym][tf].append(tf_bars[idx])
                        idx += 1

                    self._indices[sym][tf] = idx
                    history = self._history[sym][tf]
                    if history:
                        latest = history[-1]
                        if sym == self.symbol:
                            new_bars[tf] = latest
                        multi_bars[sym][tf] = latest

            if new_bars:
                yield MarketEvent(
                    timestamp=close_time,
                    bars=new_bars,
                    multi_symbol_bars=dict(multi_bars) if self.extra_symbols else {},
                )

    def get_history(
        self,
        symbol: str | None = None,
        timeframe: TF | None = None,
        lookback: int = 100,
    ) -> list[Bar]:
        sym = symbol or self.symbol
        tf = timeframe or self.base_tf
        history = self._history.get(sym, {}).get(tf, [])
        return history[-lookback:] if len(history) > lookback else list(history)

    def get_current_bar(
        self,
        symbol: str | None = None,
        timeframe: TF | None = None,
    ) -> Optional[Bar]:
        history = self.get_history(symbol, timeframe, lookback=1)
        return history[-1] if history else None

    @property
    def current_time(self) -> Optional[datetime]:
        return self._current_time

    @property
    def total_bars(self) -> int:
        return len(self._all_bars.get(self.symbol, {}).get(self.base_tf, []))

    @staticmethod
    def _bar_close_time(bar: Bar, tf: TF) -> datetime:
        duration = timedelta(minutes=tf_to_minutes(tf))
        bar_time = bar.time
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)
        return bar_time + duration

    @staticmethod
    def _bar_is_closed(bar: Bar, tf: TF, current_time: datetime) -> bool:
        close_time = MultiTimeframeDataFeed._bar_close_time(bar, tf)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        return close_time <= current_time
