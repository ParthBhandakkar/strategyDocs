"""
VP + Orderflow Absorption — Video #1 canonical strategy.

Fade absorption at developing VP extremes when aggressive orders fail at wicks
and price inverts local order clusters. Uses tick_volume wick proxies because
L2 orderflow is unavailable in Exness CSV history.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.strategies.base import BaseStrategy
from backtester.indicators.sessions import is_in_session
from backtester.indicators.volume_profile import get_developing_session_vp, near_level
from backtester.indicators.orderflow import (
    detect_buyer_absorption,
    detect_seller_absorption,
    find_recent_support_cluster,
    find_recent_resistance_cluster,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade failed absorption at developing NY session VP extremes "
        "(VWAP/POC/VAH/VAL) when wick volume shows trapped aggression "
        "and price inverts a local order cluster."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP",
            description="Build session VP after 9:30 NY open.",
            timeframe="M1",
            conditions=["Post 9:30 NY session", "Minimum 20 session bars"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption",
            description="Detect wick absorption at VP extremes.",
            timeframe="M1",
            conditions=["Buyer absorption above VAH/POC/VWAP", "Seller absorption below VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Cluster inversion",
            description="Enter on close through local order cluster.",
            timeframe="M1",
            conditions=["Short below support cluster", "Long above resistance cluster"],
        ),
    ]

    def on_start(self):
        self._absorption_bar: Bar | None = None
        self._absorption_side: str | None = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        if not is_in_session(current_time, "new_york"):
            return []

        m1_bar = bars.get(TF.M1)
        if m1_bar is None:
            return []

        m1_history = history(self.symbol, TF.M1, 300)
        if len(m1_history) < 25:
            return []

        vp = get_developing_session_vp(m1_history, current_time)
        if vp is None:
            return []

        signals: list[Signal] = []
        prior_bars = m1_history[:-1]
        if not prior_bars:
            return []

        absorption_bar = prior_bars[-1]
        current = m1_bar

        at_upper_extreme = (
            near_level(absorption_bar.high, vp.vah)
            or near_level(absorption_bar.high, vp.poc)
            or near_level(absorption_bar.high, vp.vwap)
        )
        at_lower_extreme = near_level(absorption_bar.low, vp.val)

        if at_upper_extreme and detect_buyer_absorption(absorption_bar):
            support = find_recent_support_cluster(prior_bars[:-1], lookback=10)
            if support and current.close < support:
                stop = absorption_bar.high
                risk = stop - current.close
                if risk > 0:
                    take_profit = vp.val
                    if take_profit >= current.close:
                        take_profit = current.close - risk
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=current.close,
                            stop_loss=stop,
                            take_profit=take_profit,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={
                                "setup": "short_absorption_vah",
                                "cluster": support,
                                "vp_vah": vp.vah,
                                "vp_val": vp.val,
                            },
                        )
                    )

        if at_lower_extreme and detect_seller_absorption(absorption_bar):
            resistance = find_recent_resistance_cluster(prior_bars[:-1], lookback=10)
            if resistance and current.close > resistance:
                stop = absorption_bar.low
                risk = current.close - stop
                if risk > 0:
                    take_profit = vp.vwap if vp.vwap > current.close else vp.poc
                    if take_profit <= current.close:
                        take_profit = current.close + risk
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=current.close,
                            stop_loss=stop,
                            take_profit=take_profit,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={
                                "setup": "long_absorption_val",
                                "cluster": resistance,
                                "vp_val": vp.val,
                                "vp_vwap": vp.vwap,
                            },
                        )
                    )

        return signals
