"""
VP + Orderflow Absorption — Video #1 canonical strategy.
Fade failed absorption at developing session VP extremes (post 9:30 NY).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.strategies.base import BaseStrategy
from backtester.indicators.sessions import is_post_ny_open, session_bars_since_ny_open
from backtester.indicators.orderflow_proxy import session_volume_profile, compute_vwap
from .helpers import (
    is_buyer_absorption,
    is_seller_absorption,
    recent_swing_low,
    recent_swing_high,
    near_level,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at wicks "
        "and price inverts local order clusters (post 9:30 NY)."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    # Params from video spec — not tuned on backtest data
    MIN_SESSION_BARS = 30
    LEVEL_TOLERANCE = 0.002
    SWING_LOOKBACK = 15

    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP",
            description="Build session VP from M1 bars after 9:30 NY open.",
            timeframe="M1",
            conditions=["Post 9:30 NY", "Session bars >= 30"],
            key_levels=["POC", "VAH", "VAL", "VWAP"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption at extremes",
            description="Identify wick absorption at VAH/POC (short) or VAL (long).",
            timeframe="M1",
            conditions=["Upper wick volume dominance at VAH/POC", "Lower wick at VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Order cluster inversion",
            description="Enter on close breaking recent swing cluster against absorption.",
            timeframe="M1",
            conditions=["Close below swing low after buyer absorption", "Close above swing high after seller absorption"],
        ),
    ]

    def on_start(self):
        self._pending_short_cluster: float | None = None
        self._pending_long_cluster: float | None = None
        self._absorption_high: float | None = None
        self._absorption_low: float | None = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        if not is_post_ny_open(current_time):
            return []

        m1_bar = bars.get(TF.M1)
        if not m1_bar:
            return []

        hist = history(None, TF.M1, 500)
        session_bars = session_bars_since_ny_open(hist, current_time)
        if len(session_bars) < self.MIN_SESSION_BARS:
            return []

        vp = session_volume_profile(session_bars)
        if vp is None:
            return []

        vwap = compute_vwap(session_bars)
        if vwap is None:
            return []

        signals: list[Signal] = []
        close = m1_bar.close

        # --- Short setup: buyer absorption at VAH / POC / VWAP ---
        at_upper_extreme = (
            near_level(m1_bar.high, vp.vah, self.LEVEL_TOLERANCE)
            or near_level(m1_bar.high, vp.poc, self.LEVEL_TOLERANCE)
            or near_level(m1_bar.high, vwap, self.LEVEL_TOLERANCE)
        )
        if at_upper_extreme and is_buyer_absorption(m1_bar):
            cluster = recent_swing_low(session_bars, self.SWING_LOOKBACK)
            if cluster is not None:
                self._pending_short_cluster = cluster
                self._absorption_high = m1_bar.high

        if self._pending_short_cluster is not None and close < self._pending_short_cluster:
            sl = (self._absorption_high or m1_bar.high) + m1_bar.total_range * 0.1
            risk = sl - close
            if risk > 0:
                tp = close - risk  # 1:1 to VAL
                if vp.val < close:
                    tp = max(vp.val, close - risk * 2)
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=close,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "buyer_absorption_vah", "cluster": self._pending_short_cluster},
                    )
                )
            self._pending_short_cluster = None
            self._absorption_high = None

        # --- Long setup: seller absorption at VAL ---
        at_lower_extreme = near_level(m1_bar.low, vp.val, self.LEVEL_TOLERANCE)
        if at_lower_extreme and is_seller_absorption(m1_bar):
            cluster = recent_swing_high(session_bars, self.SWING_LOOKBACK)
            if cluster is not None:
                self._pending_long_cluster = cluster
                self._absorption_low = m1_bar.low

        if self._pending_long_cluster is not None and close > self._pending_long_cluster:
            sl = (self._absorption_low or m1_bar.low) - m1_bar.total_range * 0.1
            risk = close - sl
            if risk > 0:
                tp = close + risk
                if vwap > close:
                    tp = min(vwap, close + risk * 2)
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=close,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "seller_absorption_val", "cluster": self._pending_long_cluster},
                    )
                )
            self._pending_long_cluster = None
            self._absorption_low = None

        return signals
