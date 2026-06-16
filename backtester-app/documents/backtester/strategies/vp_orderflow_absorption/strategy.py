"""
Video #1 — Orderflow and Volume Profile Day Trading Strategy.
Fade absorption at developing VP extremes; enter on order-cluster inversion.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.orderflow import detect_wick_absorption, find_volume_cluster_level
from backtester.indicators.sessions import is_post_ny_open, get_session_bars_since_ny_open
from backtester.indicators.volume_profile import VolumeProfile
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    build_session_profile,
    near_level,
    price_above_val,
    price_below_vah,
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
            "Developing VP",
            "Build session volume profile from NY 9:30 open (VWAP, POC, VAH, VAL).",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Detect wick absorption at VAH/POC/VWAP (short) or below VAL (long).",
            "M1",
        ),
        PlaybookStep(
            3,
            "Cluster Inversion",
            "Enter when M1 closes through nearby volume cluster in fade direction.",
            "M1",
        ),
    ]

    def on_start(self):
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None
        self._last_trade_day: str | None = None
        self.min_wick_ratio = 0.35
        self.min_volume = 50
        self.cluster_lookback = 8
        self.vp_proximity_pct = 0.0015

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if not m1:
            return []

        if not is_post_ny_open(current_time):
            self._reset_day_state(current_time)
            return []

        m1_hist = history(self.symbol, TF.M1, 500)
        session_bars = get_session_bars_since_ny_open(m1_hist, current_time)
        profile = build_session_profile(session_bars)
        if profile is None:
            return []

        absorption = detect_wick_absorption(
            m1,
            min_wick_ratio=self.min_wick_ratio,
            min_volume=self.min_volume,
        )
        support, resistance = find_volume_cluster_level(m1_hist, self.cluster_lookback)
        signals: list[Signal] = []

        if absorption == "buyer_absorption" and self._at_upper_vp_extreme(m1, profile):
            if support is not None:
                self._pending_short = {
                    "cluster": support,
                    "stop": m1.high,
                    "target": profile.val,
                    "absorption_high": m1.high,
                }

        if absorption == "seller_absorption" and not price_above_val(m1.close, profile):
            if m1.close < profile.val and resistance is not None:
                self._pending_long = {
                    "cluster": resistance,
                    "stop": m1.low,
                    "target": profile.vwap,
                    "absorption_low": m1.low,
                }

        if self._pending_short and support is not None:
            cluster = self._pending_short["cluster"]
            if m1.close < cluster and m1.is_bearish:
                stop = max(self._pending_short["stop"], m1.high)
                target = self._pending_short["target"]
                risk = stop - m1.close
                if risk > 0:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=m1.close,
                            stop_loss=stop,
                            take_profit=m1.close - risk,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "vp_absorption_short", "cluster": cluster},
                        )
                    )
                self._pending_short = None

        if self._pending_long and resistance is not None:
            cluster = self._pending_long["cluster"]
            if m1.close > cluster and m1.is_bullish:
                stop = min(self._pending_long["stop"], m1.low)
                risk = m1.close - stop
                if risk > 0:
                    target = self._pending_long["target"]
                    reward = max(abs(target - m1.close), risk)
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=m1.close,
                            stop_loss=stop,
                            take_profit=m1.close + reward,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "vp_absorption_long", "cluster": cluster},
                        )
                    )
                self._pending_long = None

        return signals

    def _at_upper_vp_extreme(self, bar: Bar, profile: VolumeProfile) -> bool:
        return (
            near_level(bar.high, profile.vah, self.vp_proximity_pct)
            or near_level(bar.high, profile.poc, self.vp_proximity_pct)
            or near_level(bar.high, profile.vwap, self.vp_proximity_pct)
            or price_below_vah(bar.high, profile)
        )

    def _reset_day_state(self, current_time: datetime):
        day_key = str(current_time.date())
        if self._last_trade_day != day_key:
            self._pending_short = None
            self._pending_long = None
            self._last_trade_day = day_key
