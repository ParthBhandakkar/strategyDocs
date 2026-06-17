"""
Video #1 — VP + Orderflow Absorption.
Fade failed aggressive flow at developing VP extremes after NY open.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    compute_session_vwap,
    developing_vp,
    is_buyer_absorption,
    is_seller_absorption,
    near_level,
    recent_cluster_high,
    recent_cluster_low,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at wicks "
        "and price inverts local order clusters after 9:30 NY."
    )
    timeframes = [TF.M1, TF.D1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session VP/VWAP/POC/VAH/VAL after 9:30 NY open.",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Detect buyer/seller absorption via tick_volume trapped in wicks.",
            "M1",
        ),
        PlaybookStep(
            3,
            "Cluster Inversion",
            "Enter when M1 closes through the proximate order cluster.",
            "M1",
        ),
        PlaybookStep(
            4,
            "Risk",
            "SL beyond absorption wick; TP at VAL (shorts) or VWAP (longs).",
            "M1",
        ),
    ]

    MIN_WICK_VOLUME_RATIO = 1.5
    LEVEL_TOLERANCE_PCT = 0.0005
    CLUSTER_LOOKBACK = 8
    MIN_TICK_VOLUME = 60

    def on_start(self) -> None:
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None
        self._session_day: str | None = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1_bar = bars.get(TF.M1)
        if not m1_bar:
            return []

        if not is_in_session(current_time, "new_york"):
            return []

        ny_time = get_ny_time(current_time)
        if ny_time.hour < 9 or (ny_time.hour == 9 and ny_time.minute < 30):
            return []

        day_key = ny_time.date().isoformat()
        if self._session_day != day_key:
            self._session_day = day_key
            self._pending_short = None
            self._pending_long = None

        m1_hist = history(self.symbol, TF.M1, 500)
        if len(m1_hist) < 30:
            return []

        session_bars = [
            bar
            for bar in m1_hist
            if is_in_session(bar.time, "new_york")
            and get_ny_time(bar.time).date() == ny_time.date()
            and (
                get_ny_time(bar.time).hour > 9
                or (
                    get_ny_time(bar.time).hour == 9
                    and get_ny_time(bar.time).minute >= 30
                )
            )
        ]
        if len(session_bars) < 20:
            return []

        vp = developing_vp(session_bars)
        vwap = compute_session_vwap(session_bars)
        if not vp or vwap is None:
            return []

        signals: list[Signal] = []

        at_premium = (
            near_level(m1_bar.high, vp.vah, self.LEVEL_TOLERANCE_PCT)
            or near_level(m1_bar.high, vp.poc, self.LEVEL_TOLERANCE_PCT)
            or near_level(m1_bar.high, vwap, self.LEVEL_TOLERANCE_PCT)
        )
        at_discount = near_level(m1_bar.low, vp.val, self.LEVEL_TOLERANCE_PCT)

        if at_premium and is_buyer_absorption(
            m1_bar, self.MIN_WICK_VOLUME_RATIO, self.MIN_TICK_VOLUME
        ):
            cluster_low = recent_cluster_low(m1_hist[:-1], self.CLUSTER_LOOKBACK)
            if cluster_low is not None:
                self._pending_short = {
                    "cluster": cluster_low,
                    "stop": m1_bar.high,
                    "target": vp.val,
                }
                self.step_tracker.record(
                    "Buyer Absorption",
                    2,
                    current_time,
                    m1_bar.high,
                    "M1",
                    "Buyer absorption at VP premium extreme",
                )

        if self._pending_short and m1_bar.close < self._pending_short["cluster"]:
            stop = self._pending_short["stop"]
            target = self._pending_short["target"]
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
                        metadata={"setup": "short_absorption"},
                    )
                )
            self._pending_short = None

        if at_discount and m1_bar.close < vp.val and is_seller_absorption(
            m1_bar, self.MIN_WICK_VOLUME_RATIO, self.MIN_TICK_VOLUME
        ):
            cluster_high = recent_cluster_high(m1_hist[:-1], self.CLUSTER_LOOKBACK)
            if cluster_high is not None:
                self._pending_long = {
                    "cluster": cluster_high,
                    "stop": m1_bar.low,
                    "target": vwap,
                }
                self.step_tracker.record(
                    "Seller Absorption",
                    2,
                    current_time,
                    m1_bar.low,
                    "M1",
                    "Seller absorption below VAL",
                )

        if self._pending_long and m1_bar.close > self._pending_long["cluster"]:
            stop = self._pending_long["stop"]
            target = self._pending_long["target"]
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
                        metadata={"setup": "long_absorption"},
                    )
                )
            self._pending_long = None

        return signals
