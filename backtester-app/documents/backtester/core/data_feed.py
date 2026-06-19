"""
Multi-Timeframe Data Feed.
Manages OHLCV data across multiple timeframes and symbols,
advancing time bar-by-bar and emitting MarketEvents.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional

from backtester.core import Bar
from backtester.core.bar_timing import bar_close_time
from backtester.core.timeframes import TF, sort_timeframes
from backtester.core.events import MarketEvent
from backtester.connectors.factory import DataClient


class MultiTimeframeDataFeed:
    """
    Holds bars for N timeframes (and optionally N symbols) simultaneously.
    Advances time by the smallest subscribed timeframe and emits MarketEvents
    whenever new bars complete on any subscribed timeframe.

    Bars are only released into history after their period closes, preventing
    higher-timeframe look-ahead (no peeking at full H1/H4 OHLC at bar open).
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
        self.base_tf = self.timeframes[0]  # Smallest/fastest TF
        self.start = start
        self.end = end
        self.extra_symbols = extra_symbols or []

        # Storage: symbol -> TF -> list[Bar]
        self._all_bars: dict[str, dict[TF, list[Bar]]] = defaultdict(dict)
        # Current index per symbol per TF
        self._indices: dict[str, dict[TF, int]] = defaultdict(lambda: defaultdict(int))
        # History windows for strategies to look back
        self._history: dict[str, dict[TF, list[Bar]]] = defaultdict(lambda: defaultdict(list))

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
            self._current_time = bar_close_time(base_bars[0], self.base_tf)

    def __iter__(self):
        """Iterate through time, yielding MarketEvents at each base-TF bar close."""
        if not self._loaded:
            self.load()

        base_bars = self._all_bars.get(self.symbol, {}).get(self.base_tf, [])
        if not base_bars:
            return

        for base_bar in base_bars:
            self._current_time = bar_close_time(base_bar, self.base_tf)

            new_bars: dict[TF, Bar] = {}
            multi_bars: dict[str, dict[TF, Bar]] = defaultdict(dict)

            for sym in [self.symbol] + self.extra_symbols:
                for tf in self.timeframes:
                    tf_bars = self._all_bars.get(sym, {}).get(tf, [])
                    idx = self._indices[sym][tf]

                    while idx < len(tf_bars):
                        candidate = tf_bars[idx]
                        if bar_close_time(candidate, tf) > self._current_time:
                            break
                        self._history[sym][tf].append(candidate)
                        if sym == self.symbol:
                            new_bars[tf] = candidate
                        multi_bars[sym][tf] = candidate
                        idx += 1

                    self._indices[sym][tf] = idx

            if new_bars:
                event = MarketEvent(
                    timestamp=self._current_time,
                    bars=new_bars,
                    multi_symbol_bars=dict(multi_bars) if self.extra_symbols else {},
                )
                yield event

    def get_history(self, symbol: str | None = None, timeframe: TF | None = None, lookback: int = 100) -> list[Bar]:
        """
        Get historical bars up to the current time for a specific symbol and timeframe.
        Used by strategies to look back at previous bars.
        """
        sym = symbol or self.symbol
        tf = timeframe or self.base_tf
        history = self._history.get(sym, {}).get(tf, [])
        return history[-lookback:] if len(history) > lookback else list(history)

    def get_current_bar(self, symbol: str | None = None, timeframe: TF | None = None) -> Optional[Bar]:
        """Get the most recent bar for a symbol/timeframe."""
        history = self.get_history(symbol, timeframe, lookback=1)
        return history[-1] if history else None

    @property
    def current_time(self) -> Optional[datetime]:
        return self._current_time

    @property
    def total_bars(self) -> int:
        """Total number of base-timeframe bars to process."""
        return len(self._all_bars.get(self.symbol, {}).get(self.base_tf, []))
