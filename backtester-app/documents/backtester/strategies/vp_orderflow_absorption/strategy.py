"""VP + Orderflow Absorption strategy (Video #1)."""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.strategies.base import BaseStrategy
from backtester.indicators.sessions import is_in_session, session_bars_since_ny_open
from backtester.indicators.volume_profile import compute_frvp
from .helpers import (
    detect_buyer_absorption,
    detect_seller_absorption,
    recent_swing_high,
    recent_swing_low,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes after NY open; "
        "enter on order-cluster inversion confirmed by 1M close."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP",
            description="Build session VP from 09:30 NY bars",
            timeframe="M1",
            conditions=["Post 09:30 NY", "Minimum session bars"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption",
            description="Detect wick absorption at VAH/VAL or VWAP/POC",
            timeframe="M1",
            conditions=["Wick volume dominance", "No follow-through body"],
            key_levels=["VAH", "VAL", "VWAP"],
        ),
        PlaybookStep(
            step_number=3,
            title="Inversion Entry",
            description="Enter on close through nearby order cluster",
            timeframe="M1",
            conditions=["Close below support cluster (short)", "Close above sell cluster (long)"],
            key_levels=["Local swing cluster"],
        ),
    ]

    MIN_SESSION_BARS = 30
    VAH_PROXIMITY_PCT = 0.0015
    VAL_PROXIMITY_PCT = 0.0015

    def on_start(self):
        self._pending_short_cluster: float | None = None
        self._pending_short_sl: float | None = None
        self._pending_long_cluster: float | None = None
        self._pending_long_sl: float | None = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        if not is_in_session(current_time, "ny_am"):
            return []

        m1 = bars.get(TF.M1)
        if m1 is None:
            return []

        m1_hist: list[Bar] = history(None, TF.M1, 500)
        if len(m1_hist) < self.MIN_SESSION_BARS:
            return []

        session_bars = session_bars_since_ny_open(m1_hist, current_time)
        if len(session_bars) < self.MIN_SESSION_BARS:
            return []

        vp = compute_frvp(session_bars)
        if vp is None:
            return []

        signals: list[Signal] = []
        price = m1.close
        vah_zone = abs(price - vp.vah) / max(price, 1e-9) <= self.VAH_PROXIMITY_PCT
        val_zone = abs(price - vp.val) / max(price, 1e-9) <= self.VAL_PROXIMITY_PCT
        vwap_poc_zone = (
            abs(price - vp.vwap) / max(price, 1e-9) <= self.VAH_PROXIMITY_PCT
            or abs(price - vp.poc) / max(price, 1e-9) <= self.VAH_PROXIMITY_PCT
        )

        if detect_buyer_absorption(m1) and (vah_zone or vwap_poc_zone):
            cluster = recent_swing_low(m1_hist)
            if cluster is not None:
                self._pending_short_cluster = cluster
                self._pending_short_sl = m1.high
                if self.step_tracker:
                    self.step_tracker.record(
                        "Buyer absorption at VP high",
                        2,
                        current_time,
                        m1.high,
                        "M1",
                        f"Absorption near VAH/VWAP POC at {price:.5f}",
                    )

        if detect_seller_absorption(m1) and (val_zone or vwap_poc_zone):
            cluster = recent_swing_high(m1_hist)
            if cluster is not None:
                self._pending_long_cluster = cluster
                self._pending_long_sl = m1.low
                if self.step_tracker:
                    self.step_tracker.record(
                        "Seller absorption at VP low",
                        2,
                        current_time,
                        m1.low,
                        "M1",
                        f"Absorption near VAL/VWAP at {price:.5f}",
                    )

        if self._pending_short_cluster is not None and m1.close < self._pending_short_cluster:
            sl = self._pending_short_sl or m1.high
            risk = sl - m1.close
            if risk > 0:
                tp = m1.close - risk
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=m1.close,
                        stop_loss=sl,
                        take_profit=max(tp, vp.val),
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vp_absorption_short", "target": "val"},
                    )
                )
            self._pending_short_cluster = None
            self._pending_short_sl = None

        if self._pending_long_cluster is not None and m1.close > self._pending_long_cluster:
            sl = self._pending_long_sl or m1.low
            risk = m1.close - sl
            if risk > 0:
                tp = m1.close + risk * 2
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=m1.close,
                        stop_loss=sl,
                        take_profit=min(tp, vp.vwap),
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vp_absorption_long", "target": "vwap"},
                    )
                )
            self._pending_long_cluster = None
            self._pending_long_sl = None

        return signals
