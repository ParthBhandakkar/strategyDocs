"""
Multi-Timeframe Data Feed.
Manages OHLCV data across multiple timeframes and symbols,
advancing time bar-by-bar and emitting MarketEvents.
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
    ) -> list[Bar]: ...


class MultiTimeframeDataFeed:
    """
    Holds bars for N timeframes (and optionally N symbols) simultaneously.
    Advances time by the smallest subscribed timeframe and emits MarketEvents
    whenever new bars complete on any subscribed timeframe.
    """

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
        self._history: dict[str, dict[TF, list[Bar]]] = defaultdict(
            lambda: defaultdict(list)
        )

        self._loaded = False
        self._current_time: Optional[datetime] = None

    def _bar_close_time(self, bar: Bar, tf: TF) -> datetime:
        duration = timedelta(minutes=tf_to_minutes(tf))
        close_time = bar.time + duration
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        return close_time

    def load(self):
        """Pre-fetch all data for the backtest period."""
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

    def _advance_history(self, sym: str, tf: TF) -> Optional[Bar]:
        """Advance index for a TF only when the bar has fully closed."""
        tf_bars = self._all_bars.get(sym, {}).get(tf, [])
        idx = self._indices[sym][tf]
        latest: Optional[Bar] = None

        while idx < len(tf_bars):
            bar = tf_bars[idx]
            if self._current_time is None:
                break
            if self._bar_close_time(bar, tf) <= self._current_time:
                self._history[sym][tf].append(bar)
                latest = bar
                idx += 1
            else:
                break

        self._indices[sym][tf] = idx
        return latest

    def __iter__(self):
        """Iterate through time, yielding MarketEvents."""
        if not self._loaded:
            self.load()

        base_bars = self._all_bars.get(self.symbol, {}).get(self.base_tf, [])
        if not base_bars:
            return

        prev_base_count = 0

        for base_bar in base_bars:
            self._current_time = self._bar_close_time(base_bar, self.base_tf)

            new_bars: dict[TF, Bar] = {}
            multi_bars: dict[str, dict[TF, Bar]] = defaultdict(dict)

            for sym in [self.symbol] + self.extra_symbols:
                for tf in self.timeframes:
                    latest = self._advance_history(sym, tf)
                    if latest is None:
                        continue
                    if sym == self.symbol:
                        new_bars[tf] = latest
                    multi_bars[sym][tf] = latest

            base_history = self._history[self.symbol][self.base_tf]
            if len(base_history) > prev_base_count and new_bars:
                prev_base_count = len(base_history)
                event = MarketEvent(
                    timestamp=self._current_time,
                    bars=new_bars,
                    multi_symbol_bars=dict(multi_bars) if self.extra_symbols else {},
                )
                yield event

    def get_history(
        self,
        symbol: str | None = None,
        timeframe: TF | None = None,
        lookback: int = 100,
    ) -> list[Bar]:
        """Get historical bars up to the current time for a symbol and timeframe."""
        sym = symbol or self.symbol
        tf = timeframe or self.base_tf
        history = self._history.get(sym, {}).get(tf, [])
        return history[-lookback:] if len(history) > lookback else list(history)

    def get_current_bar(
        self,
        symbol: str | None = None,
        timeframe: TF | None = None,
    ) -> Optional[Bar]:
        """Get the most recent closed bar for a symbol/timeframe."""
        history = self.get_history(symbol, timeframe, lookback=1)
        return history[-1] if history else None

    @property
    def current_time(self) -> Optional[datetime]:
        return self._current_time

    @property
    def total_bars(self) -> int:
        """Total number of base-timeframe bars to process."""
        return len(self._all_bars.get(self.symbol, {}).get(self.base_tf, []))
