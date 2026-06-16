"""
Video #1 — VP + Orderflow Absorption (Cluster A).

Fade failed aggressive orderflow at developing session VP extremes after NY open.
Uses tick_volume wick concentration as an orderflow proxy (no L2 in CSV data).
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.orderflow import (
    detect_buyer_absorption,
    detect_seller_absorption,
    nearest_swing_cluster,
)
from backtester.indicators.sessions import is_after_ny_open, is_in_session, session_bars_for_day
from backtester.indicators.volume_profile import compute_frvp, price_near_level
from backtester.strategies.base import BaseStrategy


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at wicks "
        "and price inverts local order clusters after 9:30 NY."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing Session VP",
            "Build VWAP/POC/VAH/VAL from M1 bars after 9:30 NY open.",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption at Extremes",
            "Identify wick absorption above VAH/VWAP/POC (short) or below VAL (long).",
            "M1",
        ),
        PlaybookStep(
            3,
            "Order Cluster Inversion",
            "Enter on close through local support/resistance cluster.",
            "M1",
        ),
        PlaybookStep(
            4,
            "Risk Management",
            "SL beyond absorption wick; TP at VAL (short) or VWAP (long).",
            "M1",
        ),
    ]

    LEVEL_TOLERANCE = 0.0015
    MIN_WICK_RATIO = 0.45
    SWING_LOOKBACK = 8

    def on_start(self) -> None:
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None
        self._last_session_day = None

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

        if not is_after_ny_open(current_time) or not is_in_session(current_time, "new_york"):
            return []

        m1_hist = history(self.symbol, TF.M1, 500)
        session_bars = session_bars_for_day(m1_hist, current_time)
        if len(session_bars) < 20:
            return []

        vp = compute_frvp(session_bars)
        if vp is None:
            return []

        ny_day = current_time.date()
        if self._last_session_day != ny_day:
            self._pending_short = None
            self._pending_long = None
            self._last_session_day = ny_day

        signals: list[Signal] = []
        support, resistance = nearest_swing_cluster(session_bars, self.SWING_LOOKBACK)

        at_premium = (
            price_near_level(m1_bar.high, vp.vah, self.LEVEL_TOLERANCE)
            or price_near_level(m1_bar.high, vp.vwap, self.LEVEL_TOLERANCE)
            or price_near_level(m1_bar.high, vp.poc, self.LEVEL_TOLERANCE)
        )
        at_discount = price_near_level(m1_bar.low, vp.val, self.LEVEL_TOLERANCE) or m1_bar.close < vp.val

        if at_premium and detect_buyer_absorption(m1_bar, self.MIN_WICK_RATIO):
            self._pending_short = {
                "absorption_high": m1_bar.high,
                "cluster_support": support,
                "val_target": vp.val,
            }
            if self.step_tracker:
                self.step_tracker.record(
                    "Buyer Absorption at VP",
                    2,
                    current_time,
                    m1_bar.high,
                    "M1",
                    f"Absorption near VAH/VWAP/POC at {m1_bar.high:.5f}",
                )

        if self._pending_short and m1_bar.close < self._pending_short["cluster_support"]:
            entry = m1_bar.close
            sl = self._pending_short["absorption_high"]
            risk = sl - entry
            if risk > 0:
                tp = max(self._pending_short["val_target"], entry - risk)
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vp_absorption_short"},
                    )
                )
            self._pending_short = None

        if at_discount and detect_seller_absorption(m1_bar, self.MIN_WICK_RATIO):
            self._pending_long = {
                "absorption_low": m1_bar.low,
                "cluster_resistance": resistance,
                "vwap_target": vp.vwap,
            }
            if self.step_tracker:
                self.step_tracker.record(
                    "Seller Absorption below VAL",
                    2,
                    current_time,
                    m1_bar.low,
                    "M1",
                    f"Absorption below VAL at {m1_bar.low:.5f}",
                )

        if self._pending_long and m1_bar.close > self._pending_long["cluster_resistance"]:
            entry = m1_bar.close
            sl = self._pending_long["absorption_low"]
            risk = entry - sl
            if risk > 0:
                tp = min(self._pending_long["vwap_target"], entry + risk * 2)
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vp_absorption_long"},
                    )
                )
            self._pending_long = None

        return signals
