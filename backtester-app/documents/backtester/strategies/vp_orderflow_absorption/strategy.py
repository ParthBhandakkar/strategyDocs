"""
VP + Orderflow Absorption — Video #1 canonical strategy.

Fade absorption at developing VP extremes when aggressive orders fail at wicks
and price inverts local order clusters. Post 9:30 NY session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.volume_profile import compute_frvp
from backtester.indicators.orderflow import (
    detect_buyer_absorption,
    detect_seller_absorption,
    find_support_cluster,
    find_resistance_cluster,
)
from backtester.strategies.base import BaseStrategy


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at wicks "
        "and price inverts order clusters. Post 9:30 NY open."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            step_number=1,
            title="Build Developing VP",
            description="After 9:30 NY, compute session VWAP/POC/VAH/VAL from M1 bars.",
            timeframe="M1",
            conditions=["Post 9:30 NY session"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Detect Absorption",
            description="Identify heavy tick_volume in wicks without follow-through.",
            timeframe="M1",
            conditions=["Buyer absorption above VAH/POC", "Seller absorption below VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Order Inversion Entry",
            description="Enter on close breaking local support/resistance cluster.",
            timeframe="M1",
            conditions=["Close below support cluster for short", "Close above resistance for long"],
        ),
    ]

    MIN_WICK_RATIO = 0.55
    CLUSTER_LOOKBACK = 5
    VP_PROXIMITY = 0.0015

    def on_start(self):
        self._last_trade_day: str | None = None
        self._absorption_high: float | None = None
        self._absorption_low: float | None = None

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
        if ny_time.hour < 9 or (ny_time.hour == 9 and ny_time.minute < 30):
            return []

        m1_history = history(None, TF.M1, 500)
        if len(m1_history) < 30:
            return []

        session_bars = self._session_bars(m1_history, current_time)
        if len(session_bars) < 20:
            return []

        vp = compute_frvp(session_bars)
        if vp is None:
            return []

        signals: list[Signal] = []
        day_key = ny_time.date().isoformat()
        if self._last_trade_day == day_key:
            return []

        proximity = m1.close * self.VP_PROXIMITY

        # Short: buyer absorption at VAH/POC/VWAP, then close below support cluster
        at_premium = (
            m1.close >= vp.vah - proximity
            or abs(m1.close - vp.poc) <= proximity
            or abs(m1.close - vp.vwap) <= proximity
        )
        if at_premium and detect_buyer_absorption(m1, self.MIN_WICK_RATIO):
            self._absorption_high = m1.high
            support = find_support_cluster(m1_history[:-1], self.CLUSTER_LOOKBACK)
            if support and m1.close < support:
                sl = (self._absorption_high or m1.high) + m1.total_range * 0.1
                tp = vp.val
                if sl > m1.close and tp < m1.close:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=m1.close,
                            stop_loss=sl,
                            take_profit=tp,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "buyer_absorption_short", "vah": vp.vah},
                        )
                    )
                    self._last_trade_day = day_key

        # Long: seller absorption below VAL, then close above resistance cluster
        at_discount = m1.close <= vp.val + proximity
        if not signals and at_discount and detect_seller_absorption(m1, self.MIN_WICK_RATIO):
            self._absorption_low = m1.low
            resistance = find_resistance_cluster(m1_history[:-1], self.CLUSTER_LOOKBACK)
            if resistance and m1.close > resistance:
                sl = (self._absorption_low or m1.low) - m1.total_range * 0.1
                tp = vp.vwap
                if sl < m1.close and tp > m1.close:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=m1.close,
                            stop_loss=sl,
                            take_profit=tp,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "seller_absorption_long", "val": vp.val},
                        )
                    )
                    self._last_trade_day = day_key

        return signals

    def _session_bars(self, history: list[Bar], current_time: datetime) -> list[Bar]:
        """M1 bars from 9:30 NY today through current bar."""
        ny_now = get_ny_time(current_time)
        session_start = ny_now.replace(hour=9, minute=30, second=0, microsecond=0)
        result: list[Bar] = []
        for bar in history:
            ny_bar = get_ny_time(bar.time)
            if ny_bar.date() == ny_now.date() and ny_bar >= session_start:
                result.append(bar)
        return result
