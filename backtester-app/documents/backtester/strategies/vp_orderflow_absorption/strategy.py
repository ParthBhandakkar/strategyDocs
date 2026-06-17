"""
VP + Orderflow Absorption — fade failed auctions at developing VP extremes.
Video #1 canonical: post-9:30 NY, M1 execution with session developing VP.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Direction, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.orderflow import is_buyer_absorption, is_seller_absorption
from backtester.indicators.sessions import is_post_ny_open
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    developing_session_vp,
    near_level,
    recent_resistance_cluster,
    recent_support_cluster,
    session_vwap,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes after NY open: "
        "short buyer absorption at VAH/POC/VWAP; long seller absorption below VAL."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session volume profile from 9:30 NY M1 bars.",
            "M1",
            ["Post 9:30 NY"],
            ["POC", "VAH", "VAL", "VWAP"],
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Identify wick-trapped aggressive volume at VP extremes.",
            "M1",
            ["Upper wick buyer absorption at VAH/POC", "Lower wick seller absorption below VAL"],
            [],
        ),
        PlaybookStep(
            3,
            "Inversion Entry",
            "Enter on close through nearby order cluster (swing proxy).",
            "M1",
            ["Short below support cluster after VAH absorption", "Long above resistance cluster after VAL absorption"],
            [],
        ),
    ]

    def on_start(self):
        self._pending_short_absorption: dict[str, float] = {}
        self._pending_long_absorption: dict[str, float] = {}
        self._last_session_day: str | None = None

    def _reset_daily_state(self, day_key: str):
        if self._last_session_day != day_key:
            self._pending_short_absorption.clear()
            self._pending_long_absorption.clear()
            self._last_session_day = day_key

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if not m1 or not is_post_ny_open(current_time):
            return []

        day_key = current_time.date().isoformat()
        self._reset_daily_state(day_key)

        m1_hist = history(self.symbol, TF.M1, 500)
        if len(m1_hist) < 30:
            return []

        vp = developing_session_vp(m1_hist, current_time)
        if vp is None:
            return []

        vwap = session_vwap(m1_hist, current_time)
        signals: list[Signal] = []

        at_upper_vp = (
            near_level(m1.high, vp.vah)
            or near_level(m1.high, vp.poc)
            or (vwap is not None and near_level(m1.high, vwap))
        )
        at_lower_vp = near_level(m1.low, vp.val)

        if at_upper_vp and is_buyer_absorption(m1):
            self._pending_short_absorption[day_key] = m1.high
            if self.step_tracker:
                self.step_tracker.record(
                    "Buyer Absorption at VP High",
                    2,
                    current_time,
                    m1.high,
                    "M1",
                    f"Absorption wick at VAH/POC/VWAP zone, high={m1.high:.5f}",
                )

        if at_lower_vp and is_seller_absorption(m1):
            self._pending_long_absorption[day_key] = m1.low
            if self.step_tracker:
                self.step_tracker.record(
                    "Seller Absorption below VAL",
                    2,
                    current_time,
                    m1.low,
                    "M1",
                    f"Absorption wick below VAL, low={m1.low:.5f}",
                )

        support = recent_support_cluster(m1_hist)
        resistance = recent_resistance_cluster(m1_hist)

        if day_key in self._pending_short_absorption and support is not None:
            abs_high = self._pending_short_absorption[day_key]
            if m1.close < support and m1.is_bearish:
                stop = abs_high + m1.total_range * 0.15
                risk = stop - m1.close
                if risk > 0:
                    tp = m1.close - risk
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=m1.close,
                            stop_loss=stop,
                            take_profit=max(tp, vp.val),
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "vah_absorption_inversion", "target": "val"},
                        )
                    )
                    self._pending_short_absorption.pop(day_key, None)

        if day_key in self._pending_long_absorption and resistance is not None:
            abs_low = self._pending_long_absorption[day_key]
            if m1.close > resistance and m1.is_bullish:
                stop = abs_low - m1.total_range * 0.15
                risk = m1.close - stop
                if risk > 0:
                    tp = m1.close + risk * 2
                    vwap_target = vwap if vwap else m1.close + risk
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=m1.close,
                            stop_loss=stop,
                            take_profit=max(tp, vwap_target),
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "val_absorption_inversion", "target": "vwap"},
                        )
                    )
                    self._pending_long_absorption.pop(day_key, None)

        return signals
