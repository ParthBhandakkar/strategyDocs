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


class DataClient(Protocol):
    def get_bars(
        self,
        symbol: str,
        timeframe: TF,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        ...


class MultiTimeframeDataFeed:
    """
    Holds bars for N timeframes (and optionally N symbols) simultaneously.
    Advances time by the smallest subscribed timeframe and emits MarketEvents
    whenever new bars complete on any subscribed timeframe.
    """

    def __init__(
        self,
        client: DataClient,
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
        self._last_emitted: dict[str, dict[TF, Optional[Bar]]] = defaultdict(lambda: defaultdict(lambda: None))

        self._loaded = False
        self._current_time: Optional[datetime] = None

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
            self._current_time = base_bars[0].time

    def __iter__(self):
        """Iterate through time, yielding MarketEvents."""
        if not self._loaded:
            self.load()

        base_bars = self._all_bars.get(self.symbol, {}).get(self.base_tf, [])
        if not base_bars:
            return

        for base_bar in base_bars:
            self._current_time = base_bar.time

            new_bars: dict[TF, Bar] = {}
            multi_bars: dict[str, dict[TF, Bar]] = defaultdict(dict)

            for sym in [self.symbol] + self.extra_symbols:
                for tf in self.timeframes:
                    tf_bars = self._all_bars.get(sym, {}).get(tf, [])
                    idx = self._indices[sym][tf]

                    while idx < len(tf_bars) and tf_bars[idx].time <= self._current_time:
                        candidate = tf_bars[idx]
                        if self._bar_is_closed(candidate, tf, self._current_time):
                            self._history[sym][tf].append(candidate)
                            self._last_emitted[sym][tf] = candidate
                        idx += 1

                    self._indices[sym][tf] = idx

                    latest = self._last_emitted[sym][tf]
                    if latest is not None:
                        if sym == self.symbol:
                            new_bars[tf] = latest
                        multi_bars[sym][tf] = latest

            if new_bars:
                event = MarketEvent(
                    timestamp=self._current_time,
                    bars=new_bars,
                    multi_symbol_bars=dict(multi_bars) if self.extra_symbols else {},
                )
                yield event

    def _bar_is_closed(self, bar: Bar, tf: TF, current_time: datetime) -> bool:
        """HTF bars enter history only after their period closes."""
        bar_time = bar.time
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)
        current = current_time
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        close_time = bar_time + timedelta(minutes=tf_to_minutes(tf))
        return close_time <= current

    def get_history(
        self,
        symbol: str | None = None,
        timeframe: TF | None = None,
        lookback: int = 100,
    ) -> list[Bar]:
        """Get historical bars up to the current time."""
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
