"""
Video #1 — VP Orderflow Absorption (canonical cluster A).

Fade absorption at developing VP extremes when aggressive orders fail at wicks
and price inverts nearby order clusters. Post 9:30 NY session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Direction, OrderType, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.orderflow import (
    detect_buyer_absorption,
    detect_seller_absorption,
    find_resistance_cluster,
    find_support_cluster,
)
from backtester.indicators.sessions import get_ny_time, is_post_ny_open
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    developing_session_vp,
    in_lower_value,
    in_upper_value,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail "
        "at wicks and price inverts order clusters after NY open."
    )
    timeframes = [TF.M1, TF.D1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP",
            description="Track VWAP/POC/VAH/VAL from session volume profile.",
            timeframe="D1/M1",
            conditions=["Post 9:30 NY session"],
            key_levels=["POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption",
            description="Detect heavy volume in wicks without follow-through.",
            timeframe="M1",
            conditions=["Buyer absorption above VAH", "Seller absorption below VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Cluster inversion",
            description="Enter on close through nearby support/resistance cluster.",
            timeframe="M1",
            conditions=["Close below support cluster for shorts", "Close above resistance cluster for longs"],
        ),
    ]

    def on_start(self):
        self._min_wick_ratio = 1.5
        self._cluster_lookback = 8
        self._default_rr = 1.0
        self._last_signal_day = None

    def _pip_tolerance(self, bars: list[Bar]) -> float:
        if not bars:
            return 0.0005
        price = bars[-1].close
        if price > 100:
            return 0.5
        if price > 10:
            return 0.05
        return 0.0005

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        m1_bar = bars.get(TF.M1)
        if m1_bar is None:
            return []

        if not is_post_ny_open(current_time):
            return []

        m1_history = history(self.symbol, TF.M1, 200)
        d1_history = history(self.symbol, TF.D1, 30)
        if len(m1_history) < 20 or len(d1_history) < 3:
            return []

        ny_day = get_ny_time(current_time).date()
        if self._last_signal_day == ny_day:
            return []

        vp = developing_session_vp(d1_history, m1_history)
        if vp is None:
            return []

        tolerance = self._pip_tolerance(m1_history)
        signals: list[Signal] = []

        short_setup = in_upper_value(m1_bar, vp, tolerance)
        if short_setup and detect_buyer_absorption(m1_bar, self._min_wick_ratio):
            cluster = find_support_cluster(m1_history, self._cluster_lookback)
            if cluster and m1_bar.close < cluster and m1_bar.is_bearish:
                sl = m1_bar.high + tolerance
                risk = sl - m1_bar.close
                if risk > 0:
                    tp = m1_bar.close - risk * self._default_rr
                    if tp > vp.val:
                        tp = vp.val
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=m1_bar.close,
                            stop_loss=sl,
                            take_profit=tp,
                            timestamp=current_time,
                            symbol=self.symbol,
                            order_type=OrderType.MARKET,
                            metadata={"setup": "vah_absorption_short", "cluster": cluster},
                        )
                    )
                    self._last_signal_day = ny_day
                    return signals

        long_setup = in_lower_value(m1_bar, vp, tolerance)
        if long_setup and detect_seller_absorption(m1_bar, self._min_wick_ratio):
            cluster = find_resistance_cluster(m1_history, self._cluster_lookback)
            if cluster and m1_bar.close > cluster and m1_bar.is_bullish:
                sl = m1_bar.low - tolerance
                risk = m1_bar.close - sl
                if risk > 0:
                    tp = m1_bar.close + risk * self._default_rr
                    if tp < vp.poc:
                        tp = vp.poc
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=m1_bar.close,
                            stop_loss=sl,
                            take_profit=tp,
                            timestamp=current_time,
                            symbol=self.symbol,
                            order_type=OrderType.MARKET,
                            metadata={"setup": "val_absorption_long", "cluster": cluster},
                        )
                    )
                    self._last_signal_day = ny_day

        return signals
