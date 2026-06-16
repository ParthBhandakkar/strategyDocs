"""
Video #1 — VP + Orderflow Absorption (canonical cluster A).
Fade absorption at developing VP extremes; invert on cluster break.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Direction, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.orderflow import (
    is_buyer_absorption,
    is_seller_absorption,
    recent_support_cluster,
)
from backtester.indicators.sessions import is_after_ny_open
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    developing_session_vp,
    near_level,
    session_bars_for_vp,
    vwap_proxy,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Post-9:30 NY developing volume profile fade: buyer absorption at VAH/POC/VWAP "
        "for shorts; seller absorption below VAL for longs; entry on cluster inversion."
    )
    timeframes = [TF.M1, TF.D1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session VP from 9:30 NY M1 bars (POC, VAH, VAL, VWAP proxy).",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Detect wick-heavy volume without follow-through at VP extremes.",
            "M1",
        ),
        PlaybookStep(
            3,
            "Inversion Entry",
            "Enter on close through nearby order cluster (support/resistance proxy).",
            "M1",
        ),
    ]

    def on_start(self):
        self._pending_short = False
        self._pending_long = False
        self._absorption_high = 0.0
        self._absorption_low = 0.0
        self._support_cluster = 0.0
        self._resistance_cluster = 0.0
        self.min_wick_ratio = 0.45
        self.min_absorption_volume = 50
        self.vp_touch_tolerance_pct = 0.0015
        self.cluster_lookback = 8

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if not m1 or not is_after_ny_open(current_time):
            return []

        m1_hist = history(self.symbol, TF.M1, 500)
        if len(m1_hist) < 30:
            return []

        vp = developing_session_vp(m1_hist, current_time)
        if vp is None:
            return []

        session_bars = session_bars_for_vp(m1_hist, current_time)
        vwap = vwap_proxy(session_bars)
        tolerance = self.vp_touch_tolerance_pct

        at_upper_extreme = (
            near_level(m1.high, vp.vah, tolerance)
            or near_level(m1.high, vp.poc, tolerance)
            or near_level(m1.high, vwap, tolerance)
        )
        at_lower_extreme = near_level(m1.low, vp.val, tolerance)

        if at_upper_extreme and is_buyer_absorption(
            m1,
            min_wick_ratio=self.min_wick_ratio,
            min_volume=self.min_absorption_volume,
        ):
            self._pending_short = True
            self._absorption_high = m1.high
            support = recent_support_cluster(m1_hist, self.cluster_lookback)
            if support:
                self._support_cluster = support
            self.step_tracker.record(
                "Buyer Absorption",
                2,
                current_time,
                m1.high,
                "M1",
                f"Buyer absorption near VAH/POC/VWAP at {m1.high:.5f}",
            )

        if at_lower_extreme and is_seller_absorption(
            m1,
            min_wick_ratio=self.min_wick_ratio,
            min_volume=self.min_absorption_volume,
        ):
            self._pending_long = True
            self._absorption_low = m1.low
            resistance = max(b.high for b in m1_hist[-self.cluster_lookback :])
            self._resistance_cluster = resistance
            self.step_tracker.record(
                "Seller Absorption",
                2,
                current_time,
                m1.low,
                "M1",
                f"Seller absorption below VAL at {m1.low:.5f}",
            )

        signals: list[Signal] = []

        if (
            self._pending_short
            and self._support_cluster > 0
            and m1.close < self._support_cluster
            and m1.is_bearish
        ):
            entry = m1.close
            stop = max(self._absorption_high, m1.high)
            target = vp.val if vp.val < entry else entry - (stop - entry)
            if target < entry:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=target,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vp_absorption_short"},
                    )
                )
            self._pending_short = False

        if (
            self._pending_long
            and self._resistance_cluster > 0
            and m1.close > self._resistance_cluster
            and m1.is_bullish
        ):
            entry = m1.close
            stop = min(self._absorption_low, m1.low)
            target = vwap if vwap > entry else entry + (entry - stop) * 2
            if target > entry:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=target,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vp_absorption_long"},
                    )
                )
            self._pending_long = False

        return signals
