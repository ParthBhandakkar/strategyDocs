"""
Video #1 — VP + Orderflow Absorption (Cluster A).

Proxies L2 orderflow absorption using tick_volume concentration in candle wicks,
combined with developing session volume profile (VWAP/POC/VAH/VAL).
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import is_after_ny_open
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    detect_buyer_absorption,
    detect_seller_absorption,
    developing_profile,
    near_level,
    recent_swing_high,
    recent_swing_low,
    session_bars_since_open,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at wicks "
        "and price inverts local order clusters after NY open."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            1,
            "Session VP",
            "Build developing volume profile from NY open on M1.",
            "M1",
            ["Post 9:30 NY"],
            ["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Identify wick absorption at VAH/VWAP/POC (short) or below VAL (long).",
            "M1",
            ["Wick volume cluster without follow-through"],
            ["VAH", "VAL"],
        ),
        PlaybookStep(
            3,
            "Inversion Trigger",
            "Enter on close through local order cluster (swing proxy).",
            "M1",
            ["Close below support cluster for shorts", "Close above sell cluster for longs"],
            [],
        ),
    ]

    def on_start(self):
        self._last_absorption_high: float | None = None
        self._last_absorption_low: float | None = None
        self._pending_short_cluster: float | None = None
        self._pending_long_cluster: float | None = None

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

        hist = history(self.symbol, TF.M1, 500)
        if len(hist) < 30:
            return []

        session = session_bars_since_open(hist, m1)
        profile = developing_profile(session)
        if profile is None:
            return []

        signals: list[Signal] = []

        at_upper_extreme = (
            near_level(m1.high, profile.vah)
            or near_level(m1.high, profile.vwap)
            or near_level(m1.high, profile.poc)
        )
        if at_upper_extreme and detect_buyer_absorption(m1):
            swing_low = recent_swing_low(hist)
            if swing_low:
                self._pending_short_cluster = swing_low
                self._last_absorption_high = m1.high

        if (
            self._pending_short_cluster is not None
            and m1.close < self._pending_short_cluster
            and m1.is_bearish
        ):
            stop = self._last_absorption_high or m1.high
            risk = stop - m1.close
            if risk > 0:
                take_profit = m1.close - risk
                if profile.val < m1.close:
                    take_profit = profile.val
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=m1.close,
                        stop_loss=stop,
                        take_profit=take_profit,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vah_absorption_inversion", "target": "val"},
                    )
                )
            self._pending_short_cluster = None
            self._last_absorption_high = None

        below_val = m1.close < profile.val or m1.low < profile.val
        if below_val and detect_seller_absorption(m1):
            swing_high = recent_swing_high(hist)
            if swing_high:
                self._pending_long_cluster = swing_high
                self._last_absorption_low = m1.low

        if (
            self._pending_long_cluster is not None
            and m1.close > self._pending_long_cluster
            and m1.is_bullish
        ):
            stop = self._last_absorption_low or m1.low
            risk = m1.close - stop
            if risk > 0:
                take_profit = m1.close + risk * 2
                if profile.vwap > m1.close:
                    take_profit = profile.vwap
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=m1.close,
                        stop_loss=stop,
                        take_profit=take_profit,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "val_absorption_inversion", "target": "vwap"},
                    )
                )
            self._pending_long_cluster = None
            self._last_absorption_low = None

        return signals
