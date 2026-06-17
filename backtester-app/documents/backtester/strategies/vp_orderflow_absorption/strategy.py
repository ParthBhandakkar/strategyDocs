"""
Video #1 — VP + Orderflow Absorption (canonical cluster A).

Fade absorption at developing VP extremes when aggressive orders fail at wicks
and price inverts local order clusters after NY open.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Direction, PlaybookStep, Signal
from backtester.core.broker import pip_size_for_symbol
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, get_session_bars_since_open, is_after_ny_open
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    compute_developing_vp,
    find_recent_resistance_cluster,
    find_recent_support_cluster,
    is_buyer_absorption,
    is_seller_absorption,
    near_level,
    volume_threshold_from_history,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Post-9:30 NY developing VP fade: short buyer absorption at VAH/POC/VWAP "
        "with close below local support cluster; long seller absorption below VAL."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP",
            description="Build session volume profile from NY open bars.",
            timeframe="M1",
            conditions=["After 9:30 NY", "Use session M1 bars only"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption",
            description="Detect wick-heavy volume without follow-through.",
            timeframe="M1",
            conditions=["Buyer absorption at highs", "Seller absorption at lows"],
            key_levels=["VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Cluster inversion",
            description="Enter on close through nearby order cluster.",
            timeframe="M1",
            conditions=["Short below support cluster", "Long above resistance cluster"],
            key_levels=["Local cluster"],
        ),
    ]

    def on_start(self):
        self._last_session_date = None
        self._trades_today = 0

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        if TF.M1 not in bars:
            return []

        bar = bars[TF.M1]
        if not is_after_ny_open(current_time):
            return []

        ny_date = get_ny_time(current_time).date()
        if self._last_session_date != ny_date:
            self._last_session_date = ny_date
            self._trades_today = 0

        if self._trades_today >= 3:
            return []

        m1_history = history(None, TF.M1, 500)
        session_bars = get_session_bars_since_open(m1_history, current_time)
        if len(session_bars) < 15:
            return []

        vp = compute_developing_vp(session_bars)
        if vp is None:
            return []

        vol_threshold = volume_threshold_from_history(session_bars)
        pip = pip_size_for_symbol(self.symbol)
        buffer = pip * 2

        signals: list[Signal] = []

        premium_touch = (
            near_level(bar.high, vp.vah)
            or near_level(bar.high, vp.poc)
            or near_level(bar.high, vp.vwap)
        )
        discount_touch = bar.close < vp.val or near_level(bar.low, vp.val)

        if premium_touch and len(session_bars) >= 3:
            prior = session_bars[:-1]
            if any(is_buyer_absorption(b, vol_threshold) for b in prior[-5:]):
                cluster = find_recent_support_cluster(session_bars)
                if cluster and bar.close < cluster[0]:
                    stop = max(bar.high, cluster[1]) + buffer
                    target = vp.val
                    risk = stop - bar.close
                    reward = bar.close - target
                    if risk > 0 and reward > 0:
                        signals.append(
                            Signal(
                                strategy_id=self.id,
                                direction=Direction.SHORT,
                                entry_price=bar.close,
                                stop_loss=stop,
                                take_profit=target,
                                timestamp=current_time,
                                symbol=self.symbol,
                                metadata={"setup": "premium_absorption_short", "vah": vp.vah},
                            )
                        )
                        self._trades_today += 1

        if discount_touch and len(session_bars) >= 3:
            prior = session_bars[:-1]
            if any(is_seller_absorption(b, vol_threshold) for b in prior[-5:]):
                cluster = find_recent_resistance_cluster(session_bars)
                if cluster and bar.is_bullish and bar.close > cluster[1]:
                    stop = min(bar.low, cluster[0]) - buffer
                    target = vp.vwap if vp.vwap > bar.close else vp.poc
                    risk = bar.close - stop
                    reward = target - bar.close
                    if risk > 0 and reward > 0:
                        signals.append(
                            Signal(
                                strategy_id=self.id,
                                direction=Direction.LONG,
                                entry_price=bar.close,
                                stop_loss=stop,
                                take_profit=target,
                                timestamp=current_time,
                                symbol=self.symbol,
                                metadata={"setup": "discount_absorption_long", "val": vp.val},
                            )
                        )
                        self._trades_today += 1

        return signals
