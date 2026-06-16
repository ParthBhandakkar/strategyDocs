"""
Video #1: Orderflow and Volume Profile Day Trading Strategy.
Fade absorption at developing VP extremes; order-cluster inversion on M1.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.orderflow import (
    is_buyer_absorption,
    is_seller_absorption,
    find_recent_support_cluster,
    find_recent_resistance_cluster,
)
from backtester.indicators.sessions import is_post_ny_open, filter_session_bars, get_ny_time
from backtester.indicators.volume_profile import compute_developing_session_vp
from backtester.strategies.base import BaseStrategy


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Post-9:30 NY developing VP: fade buyer absorption at VAH/VWAP/POC "
        "and seller absorption below VAL with order-cluster inversion on M1."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session VP (VWAP/POC/VAH/VAL) from 9:30 NY open.",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption Detection",
            "Identify wick absorption at VAH (shorts) or below VAL (longs).",
            "M1",
        ),
        PlaybookStep(
            3,
            "Order Inversion",
            "Enter on M1 close through nearby order cluster (support/resistance flip).",
            "M1",
        ),
        PlaybookStep(
            4,
            "Risk Management",
            "SL beyond absorption wick; TP at VAL (short) or VWAP (long).",
            "M1",
        ),
    ]

    def on_start(self):
        self._session_day = None
        self._last_signal_bar = None
        self._pending_short_cluster: float | None = None
        self._pending_long_cluster: float | None = None
        self._absorption_high: float | None = None
        self._absorption_low: float | None = None

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
            return []

        ny_day = get_ny_time(current_time).date()
        if self._session_day != ny_day:
            self._session_day = ny_day
            self._pending_short_cluster = None
            self._pending_long_cluster = None
            self._absorption_high = None
            self._absorption_low = None

        if self.broker and self.broker.has_open_position(self.id):
            return []

        m1_hist = history(self.symbol, TF.M1, 500)
        session_bars = filter_session_bars(m1_hist, "ny_open", current_time)
        if len(session_bars) < 30:
            return []

        vp = compute_developing_session_vp(session_bars)
        if vp is None:
            return []

        signals: list[Signal] = []

        at_vah_zone = m1.high >= vp.vah * 0.9995 or abs(m1.close - vp.poc) / vp.poc < 0.001
        below_val = m1.close < vp.val

        if at_vah_zone and is_buyer_absorption(m1):
            cluster = find_recent_support_cluster(session_bars[-12:])
            if cluster:
                self._pending_short_cluster = cluster
                self._absorption_high = m1.high
                if self.step_tracker:
                    self.step_tracker.record(
                        "Buyer Absorption at VAH/POC",
                        2,
                        current_time,
                        m1.high,
                        "M1",
                        f"Absorption wick high {m1.high:.5f} near VAH {vp.vah:.5f}",
                    )

        if (
            self._pending_short_cluster is not None
            and self._absorption_high is not None
            and m1.is_bearish
            and m1.close < self._pending_short_cluster
        ):
            entry = m1.close
            sl = self._absorption_high + (self._absorption_high - m1.low) * 0.1
            risk = sl - entry
            if risk > 0:
                tp = entry - risk
                if vp.val < entry:
                    tp = max(vp.val, entry - risk * 2)
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vah_absorption_inversion", "vah": vp.vah},
                    )
                )
                self._pending_short_cluster = None
                self._absorption_high = None

        if below_val and is_seller_absorption(m1):
            cluster = find_recent_resistance_cluster(session_bars[-12:])
            if cluster:
                self._pending_long_cluster = cluster
                self._absorption_low = m1.low
                if self.step_tracker:
                    self.step_tracker.record(
                        "Seller Absorption below VAL",
                        2,
                        current_time,
                        m1.low,
                        "M1",
                        f"Absorption wick low {m1.low:.5f} below VAL {vp.val:.5f}",
                    )

        if (
            self._pending_long_cluster is not None
            and self._absorption_low is not None
            and m1.is_bullish
            and m1.close > self._pending_long_cluster
        ):
            entry = m1.close
            sl = self._absorption_low - (m1.high - self._absorption_low) * 0.1
            risk = entry - sl
            if risk > 0:
                tp = entry + risk * 2
                if vp.vwap > entry:
                    tp = vp.vwap
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "val_absorption_inversion", "val": vp.val},
                    )
                )
                self._pending_long_cluster = None
                self._absorption_low = None

        if signals:
            self._last_signal_bar = current_time

        return signals
