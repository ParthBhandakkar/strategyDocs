"""VP + orderflow absorption strategy (Video #1)."""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Direction, OrderType, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    average_tick_volume,
    detect_buyer_absorption,
    detect_seller_absorption,
    local_support_level,
    near_level,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
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
            title="Developing VP",
            description="Build session VWAP/POC/VAH/VAL from post-9:30 NY M1 bars.",
            timeframe="M1",
            conditions=["After 9:30 NY", "Minimum session bars accumulated"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption",
            description="Identify wick-localized volume without follow-through.",
            timeframe="M1",
            conditions=["Buyer absorption above VAH/POC/VWAP", "Seller absorption below VAL"],
            key_levels=["VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Inversion Entry",
            description="Enter on close through nearby order cluster.",
            timeframe="M1",
            conditions=["Close below local support for shorts", "Close above cluster for longs"],
            key_levels=["Local cluster", "VAL", "VWAP"],
        ),
    ]

    MIN_SESSION_BARS = 30
    CLUSTER_LOOKBACK = 8
    VOLUME_RATIO = 1.5

    def on_start(self):
        self._session_date = None
        self._session_bars: list[Bar] = []
        self._pending_short_absorption_high: float | None = None
        self._pending_long_absorption_low: float | None = None

    def _reset_session(self, ny_date):
        self._session_date = ny_date
        self._session_bars = []
        self._pending_short_absorption_high = None
        self._pending_long_absorption_low = None

    def _session_bars_for_day(self, history, current_time: datetime) -> list[Bar]:
        ny_now = get_ny_time(current_time)
        if self._session_date != ny_now.date():
            self._reset_session(ny_now.date())

        all_bars = history(None, TF.M1, 5000)
        session_bars = [
            bar
            for bar in all_bars
            if get_ny_time(bar.time).date() == ny_now.date() and is_in_session(bar.time, "ny_am")
        ]
        self._session_bars = session_bars
        return session_bars

    def on_bar(self, bars, history, multi_symbol_bars, current_time):
        if TF.M1 not in bars:
            return []

        if not is_in_session(current_time, "ny_am"):
            return []

        bar = bars[TF.M1]
        session_bars = self._session_bars_for_day(history, current_time)
        if len(session_bars) < self.MIN_SESSION_BARS:
            return []

        profile = compute_frvp(session_bars)
        if profile is None:
            return []

        prior_bars = session_bars[:-1]
        if not prior_bars:
            return []

        avg_volume = average_tick_volume(prior_bars)
        prev_bar = prior_bars[-1]
        signals: list[Signal] = []

        at_upper_extreme = (
            near_level(bar.high, profile.vah)
            or near_level(bar.high, profile.poc)
            or near_level(bar.high, profile.vwap)
        )
        below_val = bar.close < profile.val

        if at_upper_extreme and detect_buyer_absorption(prev_bar, avg_volume, self.VOLUME_RATIO):
            self._pending_short_absorption_high = prev_bar.high
            self._pending_long_absorption_low = None

        if below_val and detect_seller_absorption(prev_bar, avg_volume, self.VOLUME_RATIO):
            self._pending_long_absorption_low = prev_bar.low
            self._pending_short_absorption_high = None

        support = local_support_level(prior_bars, self.CLUSTER_LOOKBACK)
        if (
            self._pending_short_absorption_high is not None
            and support is not None
            and bar.close < support
            and bar.is_bearish
        ):
            entry = bar.close
            stop = self._pending_short_absorption_high
            risk = stop - entry
            if risk > 0:
                take_profit = entry - risk
                if profile.val < entry:
                    take_profit = profile.val
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=take_profit,
                        timestamp=current_time,
                        symbol=self.symbol,
                        order_type=OrderType.MARKET,
                        metadata={"setup": "buyer_absorption_vah", "target": "val"},
                    )
                )
                self._pending_short_absorption_high = None

        if (
            self._pending_long_absorption_low is not None
            and bar.is_bullish
            and bar.close > prev_bar.high
        ):
            entry = bar.close
            stop = self._pending_long_absorption_low
            risk = entry - stop
            if risk > 0:
                take_profit = entry + (2 * risk)
                if profile.vwap > entry:
                    take_profit = profile.vwap
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=take_profit,
                        timestamp=current_time,
                        symbol=self.symbol,
                        order_type=OrderType.MARKET,
                        metadata={"setup": "seller_absorption_val", "target": "vwap"},
                    )
                )
                self._pending_long_absorption_low = None

        return signals
