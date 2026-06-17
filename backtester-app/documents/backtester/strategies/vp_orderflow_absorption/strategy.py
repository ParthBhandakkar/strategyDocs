from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Direction, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_session_date, get_ny_time, is_post_ny_open
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    detect_buyer_absorption,
    detect_seller_absorption,
    find_recent_order_cluster,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade failed aggressive orderflow at developing daily VP extremes after NY open. "
        "Short buyer absorption above VAH/POC/VWAP; long seller absorption below VAL."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP",
            description="Build session volume profile from NY-open M1 bars.",
            timeframe="M1",
            conditions=["After 09:30 NY", "Session VP computed from M1 bars"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption",
            description="Detect aggressive order failure in candle wicks near VP extremes.",
            timeframe="M1",
            conditions=["Buyer absorption at upper wick near VAH/VWAP/POC", "Seller absorption at lower wick below VAL"],
            key_levels=["VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Cluster Inversion",
            description="Enter when price closes through the nearest high-volume order cluster.",
            timeframe="M1",
            conditions=["Short: close below support cluster", "Long: close above sell cluster"],
            key_levels=["Order cluster"],
        ),
    ]

    VP_TOUCH_BUFFER = 0.0008
    MIN_CLUSTER_VOLUME = 25

    def on_start(self):
        self._session_date = None
        self._session_bars: list[Bar] = []
        self._last_signal_bar: datetime | None = None
        self._cooldown_bars = 15

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
        if m1_bar is None:
            return []

        if self._last_signal_bar and (current_time - self._last_signal_bar).total_seconds() < self._cooldown_bars * 60:
            return []

        session_date = get_ny_session_date(current_time)
        if self._session_date != session_date:
            self._session_date = session_date
            self._session_bars = []

        self._session_bars.append(m1_bar)
        if len(self._session_bars) < 30:
            return []

        profile = compute_frvp(self._session_bars)
        if profile is None:
            return []

        m1_history = history(None, TF.M1, 20)
        cluster = find_recent_order_cluster(m1_history, lookback=12, min_volume=self.MIN_CLUSTER_VOLUME)
        if cluster is None:
            return []

        signals: list[Signal] = []
        near_vah = abs(m1_bar.high - profile.vah) <= self._buffer(profile.vah)
        near_vwap = abs(m1_bar.high - profile.vwap) <= self._buffer(profile.vwap)
        near_poc = abs(m1_bar.high - profile.poc) <= self._buffer(profile.poc)
        near_val = abs(m1_bar.low - profile.val) <= self._buffer(profile.val)

        if (near_vah or near_vwap or near_poc) and detect_buyer_absorption(m1_bar):
            if m1_bar.close < cluster.low:
                stop = max(m1_bar.high, cluster.high) + self._buffer(m1_bar.close)
                target = profile.val
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
                            metadata={"setup": "buyer_absorption_vah", "vah": profile.vah, "val": profile.val},
                        )
                    )

        below_val = m1_bar.close < profile.val or near_val
        if below_val and detect_seller_absorption(m1_bar):
            if m1_bar.close > cluster.high:
                stop = min(m1_bar.low, cluster.low) - self._buffer(m1_bar.close)
                target = profile.vwap
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
                            metadata={"setup": "seller_absorption_val", "vah": profile.vah, "val": profile.val},
                        )
                    )

        if signals:
            self._last_signal_bar = current_time
        return signals

    def _buffer(self, price: float) -> float:
        if "JPY" in self.symbol.upper():
            return 0.03
        if "XAU" in self.symbol.upper() or "BTC" in self.symbol.upper():
            return max(price * 0.0003, 0.5)
        return max(price * self.VP_TOUCH_BUFFER, 0.00005)
