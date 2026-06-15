"""
Video #1: Orderflow and Volume Profile Day Trading Strategy.
Fade absorption at developing VP extremes with order-cluster inversion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Direction, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session, session_open_today
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    compute_developing_vp,
    is_buyer_absorption_at_high,
    is_seller_absorption_at_low,
    recent_support_cluster,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing NY-session volume profile extremes when "
        "aggressive wick volume fails and price inverts nearby order clusters."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Build Developing VP",
            description="After 9:30 NY, accumulate session M1 bars and compute POC/VAH/VAL/VWAP.",
            timeframe="M1",
            conditions=["Post 9:30 NY session", "Minimum session history"],
            key_levels=["POC", "VAH", "VAL", "VWAP"],
        ),
        PlaybookStep(
            step_number=2,
            title="Detect Wick Absorption",
            description="Identify buyer/seller absorption when heavy wick volume stalls price.",
            timeframe="M1",
            conditions=["Upper wick buyer absorption above value", "Lower wick seller absorption below VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Order Cluster Inversion",
            description="Enter when price closes through the proximate support/resistance cluster.",
            timeframe="M1",
            conditions=["Short below support after VAH/POC/VWAP fade", "Long above cluster after VAL discount absorption"],
        ),
    ]

    def on_start(self):
        self._session_date = None
        self._session_bars: list[Bar] = []
        self._last_absorption_high: float | None = None
        self._last_absorption_low: float | None = None
        self._min_wick_ratio = 0.45
        self._vp_proximity_pct = 0.0015
        self._support_lookback = 8
        self._min_session_bars = 30

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        if TF.M1 not in bars:
            return []
        if not is_in_session(current_time, "new_york"):
            return []

        bar = bars[TF.M1]
        ny_time = get_ny_time(current_time)
        if ny_time.hour == 9 and ny_time.minute < 30:
            return []

        self._update_session(bar, current_time)
        if len(self._session_bars) < self._min_session_bars:
            return []

        levels = compute_developing_vp(self._session_bars)
        if levels is None:
            return []

        m1_history = history(None, TF.M1, 20)
        if len(m1_history) < 3:
            return []

        proximity = max(bar.close * self._vp_proximity_pct, 1e-5)
        signals: list[Signal] = []

        if self._detect_short_setup(bar, levels, proximity, m1_history):
            signal = self._build_short_signal(bar, levels, m1_history)
            if signal is not None:
                signals.append(signal)

        if self._detect_long_setup(bar, levels, proximity, m1_history):
            signal = self._build_long_signal(bar, levels, m1_history)
            if signal is not None:
                signals.append(signal)

        return signals

    def _update_session(self, bar: Bar, current_time: datetime) -> None:
        ny_date = get_ny_time(current_time).date()
        if self._session_date != ny_date:
            self._session_date = ny_date
            self._session_bars = []
            self._last_absorption_high = None
            self._last_absorption_low = None

        session_start = session_open_today(current_time, 9, 30)
        if bar.time >= session_start:
            self._session_bars.append(bar)

    def _detect_short_setup(self, bar: Bar, levels, proximity: float, history: list[Bar]) -> bool:
        near_vah = abs(bar.high - levels.vah) <= proximity
        near_poc = abs(bar.high - levels.poc) <= proximity
        near_vwap = abs(bar.high - levels.vwap) <= proximity
        if not (near_vah or near_poc or near_vwap):
            return False

        prior = history[-2]
        if is_buyer_absorption_at_high(prior, self._min_wick_ratio):
            self._last_absorption_high = prior.high

        support = recent_support_cluster(history, self._support_lookback)
        if support is None or self._last_absorption_high is None:
            return False
        return bar.close < support and bar.is_bearish

    def _detect_long_setup(self, bar: Bar, levels, proximity: float, history: list[Bar]) -> bool:
        if bar.close > levels.val:
            return False

        prior = history[-2]
        if is_seller_absorption_at_low(prior, self._min_wick_ratio):
            self._last_absorption_low = prior.low

        resistance = max(prior.high for prior in history[-self._support_lookback :])
        if self._last_absorption_low is None:
            return False
        return bar.is_bullish and bar.close > resistance

    def _build_short_signal(self, bar: Bar, levels, history: list[Bar]) -> Signal | None:
        if self._last_absorption_high is None:
            return None
        entry = bar.close
        stop = self._last_absorption_high
        if stop <= entry:
            return None
        risk = stop - entry
        take_profit = max(levels.val, entry - risk)
        if take_profit >= entry:
            take_profit = entry - risk
        return Signal(
            strategy_id=self.id,
            direction=Direction.SHORT,
            entry_price=entry,
            stop_loss=stop,
            take_profit=take_profit,
            timestamp=bar.time,
            symbol=self.symbol,
            metadata={"setup": "vp_absorption_short", "target": "val"},
        )

    def _build_long_signal(self, bar: Bar, levels, history: list[Bar]) -> Signal | None:
        if self._last_absorption_low is None:
            return None
        entry = bar.close
        stop = self._last_absorption_low
        if stop >= entry:
            return None
        risk = entry - stop
        take_profit = min(levels.vwap, entry + (risk * 2))
        if take_profit <= entry:
            take_profit = entry + (risk * 2)
        return Signal(
            strategy_id=self.id,
            direction=Direction.LONG,
            entry_price=entry,
            stop_loss=stop,
            take_profit=take_profit,
            timestamp=bar.time,
            symbol=self.symbol,
            metadata={"setup": "vp_absorption_long", "target": "vwap"},
        )
