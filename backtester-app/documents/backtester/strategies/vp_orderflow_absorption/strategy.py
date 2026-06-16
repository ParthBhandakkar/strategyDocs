"""
Video #1 — VP + Orderflow Absorption at developing profile extremes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Direction, OrderType, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    build_developing_vp,
    compute_session_vwap,
    detect_wick_absorption,
    find_order_cluster_level,
    near_level,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at wicks "
        "and price inverts local order clusters after the NY open."
    )
    timeframes = [TF.M1, TF.H1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Build Developing VP",
            description="After 9:30 NY, track session VWAP/POC/VAH/VAL from M1 bars.",
            timeframe="M1",
            conditions=["Post 9:30 NY session", "Minimum 20 session bars"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Detect Wick Absorption",
            description="Identify heavy tick volume trapped in wicks at VAH/POC or VAL.",
            timeframe="M1",
            conditions=["Price taps VP extreme", "Wick volume without follow-through"],
        ),
        PlaybookStep(
            step_number=3,
            title="Order Cluster Inversion",
            description="Enter when M1 closes through the local support/resistance cluster.",
            timeframe="M1",
            conditions=["Close below cluster for shorts", "Close above cluster for longs"],
        ),
    ]

    def on_start(self):
        self._session_day = None
        self._session_bars: list[Bar] = []
        self._last_signal_bar: datetime | None = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if m1 is None:
            return []

        if not is_in_session(current_time, "new_york"):
            return []

        ny_time = get_ny_time(current_time)
        if ny_time.hour == 9 and ny_time.minute < 30:
            return []

        ny_day = ny_time.date()
        if self._session_day != ny_day:
            self._session_day = ny_day
            self._session_bars = []
            self._last_signal_bar = None

        self._session_bars.append(m1)
        if len(self._session_bars) < 20:
            return []

        if self._last_signal_bar == m1.time:
            return []

        vp = build_developing_vp(self._session_bars)
        if vp is None:
            return []

        vwap = compute_session_vwap(self._session_bars)
        recent = history(None, TF.M1, 8)
        if len(recent) < 3:
            return []

        cluster_low, cluster_high = find_order_cluster_level(recent[:-1], lookback=5)
        signals: list[Signal] = []

        upper_levels = [("VAH", vp.vah), ("POC", vp.poc), ("VWAP", vwap)]
        for level_name, level in upper_levels:
            if not near_level(m1.high, level):
                continue
            if not detect_wick_absorption(m1, "buyers"):
                continue
            if m1.close >= cluster_low:
                continue
            stop_loss = max(m1.high, cluster_high) + (m1.high - m1.low) * 0.1
            risk = stop_loss - m1.close
            if risk <= 0:
                continue
            take_profit = m1.close - risk
            signals.append(
                Signal(
                    strategy_id=self.id,
                    direction=Direction.SHORT,
                    entry_price=m1.close,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    timestamp=m1.time,
                    symbol=self.symbol,
                    order_type=OrderType.MARKET,
                    metadata={"setup": f"short_{level_name}_absorption"},
                )
            )
            self._last_signal_bar = m1.time
            return signals

        lower_levels = [("VAL", vp.val)]
        for level_name, level in lower_levels:
            if not near_level(m1.low, level):
                continue
            if not detect_wick_absorption(m1, "sellers"):
                continue
            if m1.close <= cluster_high:
                continue
            stop_loss = min(m1.low, cluster_low) - (m1.high - m1.low) * 0.1
            risk = m1.close - stop_loss
            if risk <= 0:
                continue
            take_profit = m1.close + risk * 2.0
            signals.append(
                Signal(
                    strategy_id=self.id,
                    direction=Direction.LONG,
                    entry_price=m1.close,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    timestamp=m1.time,
                    symbol=self.symbol,
                    order_type=OrderType.MARKET,
                    metadata={"setup": f"long_{level_name}_absorption"},
                )
            )
            self._last_signal_bar = m1.time
            return signals

        return signals
