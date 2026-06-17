"""Video #1 — VP + Orderflow Absorption."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.orderflow import (
    detect_buyer_absorption,
    detect_seller_absorption,
    find_volume_cluster_level,
    price_near_level,
)
from backtester.indicators.sessions import is_in_session
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    compute_developing_vp,
    compute_vwap,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    module = "vp_orderflow_absorption"
    name = "Orderflow and Volume Profile Day Trading Strategy"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at wicks "
        "and price inverts local order clusters after the NY open."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Develop session VP",
            description="Build developing daily volume profile after 9:30 NY.",
            timeframe="M1",
            conditions=["Post 9:30 NY", "Minimum 20 M1 bars in session"],
            key_levels=["POC", "VAH", "VAL", "VWAP"],
        ),
        PlaybookStep(
            step_number=2,
            title="Detect wick absorption",
            description="Identify buyer/seller absorption at VP extremes using wick volume.",
            timeframe="M1",
            conditions=["Upper wick buyer absorption at VAH", "Lower wick seller absorption at VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Order cluster inversion",
            description="Enter when price closes through the local volume cluster.",
            timeframe="M1",
            conditions=["Close below support cluster for shorts", "Close above resistance cluster for longs"],
        ),
    ]

    MIN_SESSION_BARS = 20
    CLUSTER_LOOKBACK = 8
    LEVEL_TOLERANCE = 0.0015

    def on_start(self):
        self._last_trade_day = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        if not is_in_session(current_time, "post_ny_open"):
            return []

        m1_bar = bars.get(TF.M1)
        if m1_bar is None:
            return []

        day_key = current_time.date()
        if self._last_trade_day == day_key:
            return []

        m1_history = history(None, TF.M1, 5000)
        if len(m1_history) < self.MIN_SESSION_BARS + 2:
            return []

        vp = compute_developing_vp(m1_history, current_time)
        if vp is None:
            return []

        day_bars = [bar for bar in m1_history if bar.time <= current_time]
        vwap = compute_vwap(day_bars)
        prior_bars = m1_history[-(self.CLUSTER_LOOKBACK + 1):-1]
        if len(prior_bars) < 3:
            return []

        cluster_level = find_volume_cluster_level(prior_bars, self.CLUSTER_LOOKBACK)
        if cluster_level is None:
            return []

        signals: list[Signal] = []

        short_absorption = any(detect_buyer_absorption(bar) for bar in prior_bars[-3:])
        if (
            short_absorption
            and (price_near_level(m1_bar.high, vp.vah, self.LEVEL_TOLERANCE) or m1_bar.high >= vp.vah)
            and m1_bar.close < cluster_level
        ):
            absorption_high = max(bar.high for bar in prior_bars[-3:])
            stop = absorption_high
            target = vp.val if vp.val < m1_bar.close else (vwap or vp.poc)
            risk = stop - m1_bar.close
            reward = m1_bar.close - target
            if risk > 0 and reward > 0:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=m1_bar.close,
                        stop_loss=stop,
                        take_profit=target,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vah_buyer_absorption_inversion"},
                    )
                )
                self._last_trade_day = day_key
                return signals

        long_absorption = any(detect_seller_absorption(bar) for bar in prior_bars[-3:])
        if (
            long_absorption
            and (price_near_level(m1_bar.low, vp.val, self.LEVEL_TOLERANCE) or m1_bar.low <= vp.val)
            and m1_bar.close > cluster_level
        ):
            absorption_low = min(bar.low for bar in prior_bars[-3:])
            stop = absorption_low
            target = vwap or vp.poc
            if target <= m1_bar.close:
                target = vp.vah
            risk = m1_bar.close - stop
            reward = target - m1_bar.close
            if risk > 0 and reward > 0:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=m1_bar.close,
                        stop_loss=stop,
                        take_profit=target,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "val_seller_absorption_inversion"},
                    )
                )
                self._last_trade_day = day_key

        return signals
