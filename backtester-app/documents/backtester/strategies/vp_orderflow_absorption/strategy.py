from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Direction, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.orderflow import (
    detect_buyer_absorption_at_highs,
    detect_seller_absorption_at_lows,
    find_local_support_cluster,
)
from backtester.indicators.sessions import get_session_bars_since_open, is_in_session
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy

from .helpers import below_value_area, near_upper_reference


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing NY session VP extremes when aggressive flow "
        "fails at wicks and price inverts local order clusters."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build NY session volume profile from 9:30 NY open.",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Detect buyer absorption at VAH/POC/VWAP or seller absorption below VAL.",
            "M1",
        ),
        PlaybookStep(
            3,
            "Inversion Trigger",
            "Enter after close breaks the local order cluster against absorption.",
            "M1",
        ),
    ]

    min_session_bars = 30
    min_volume_multiplier = 1.2

    def on_start(self):
        self.pending_short: dict | None = None
        self.pending_long: dict | None = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        if not is_in_session(current_time, "new_york"):
            return []

        m1_bar = bars.get(TF.M1)
        if m1_bar is None:
            return []

        session_history = history(self.symbol, TF.M1, 5000)
        session_bars = get_session_bars_since_open(session_history, current_time)
        if len(session_bars) < self.min_session_bars:
            return []

        profile = compute_frvp(session_bars, row_size=80, va_pct=70.0)
        if profile is None:
            return []

        median_volume = sorted(bar.tick_volume for bar in session_bars)[len(session_bars) // 2]
        volume_threshold = max(1, median_volume * self.min_volume_multiplier)
        signals: list[Signal] = []

        if self.pending_short is None and near_upper_reference(m1_bar, profile):
            if (
                detect_buyer_absorption_at_highs(m1_bar)
                and m1_bar.tick_volume >= volume_threshold
            ):
                cluster = find_local_support_cluster(session_bars, lookback=8)
                if cluster is not None:
                    self.pending_short = {
                        "cluster": cluster,
                        "stop": m1_bar.high,
                        "target": profile.val,
                    }
                    self.step_tracker.record(
                        "Buyer Absorption",
                        2,
                        current_time,
                        m1_bar.high,
                        "M1",
                        "Buyer absorption at upper VP reference",
                    )

        if self.pending_short and m1_bar.close < self.pending_short["cluster"]:
            stop = self.pending_short["stop"]
            target = self.pending_short["target"]
            risk = stop - m1_bar.close
            if risk > 0 and target < m1_bar.close:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=m1_bar.close,
                        stop_loss=stop,
                        take_profit=target,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "short_absorption_inversion"},
                    )
                )
            self.pending_short = None

        if self.pending_long is None and below_value_area(m1_bar, profile):
            if (
                detect_seller_absorption_at_lows(m1_bar)
                and m1_bar.tick_volume >= volume_threshold
            ):
                self.pending_long = {
                    "stop": m1_bar.low,
                    "target": profile.vwap,
                }
                self.step_tracker.record(
                    "Seller Absorption",
                    2,
                    current_time,
                    m1_bar.low,
                    "M1",
                    "Seller absorption below VAL",
                )

        if self.pending_long and m1_bar.is_bullish and m1_bar.close > m1_bar.open:
            stop = self.pending_long["stop"]
            target = self.pending_long["target"]
            risk = m1_bar.close - stop
            if risk > 0 and target > m1_bar.close:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=m1_bar.close,
                        stop_loss=stop,
                        take_profit=target,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "long_absorption_reclaim"},
                    )
                )
            self.pending_long = None

        return signals
