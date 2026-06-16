"""
Video #1 — VP + Orderflow Absorption (Cluster A).
Fade absorption at developing VP extremes when aggressive orders fail at wicks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.orderflow import (
    developing_vp,
    session_vwap,
    detect_buyer_absorption,
    detect_seller_absorption,
    find_support_cluster,
    find_resistance_cluster,
    near_level,
)
from backtester.strategies.base import BaseStrategy


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Post 9:30 NY developing VP: fade buyer absorption at VAH/POC/VWAP "
        "or seller absorption below VAL when order clusters invert."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session volume profile from M1 bars after 9:30 NY open.",
            "M1",
            conditions=["Post 9:30 NY", "VWAP/POC/VAH/VAL computed from session bars"],
        ),
        PlaybookStep(
            2,
            "Absorption at Extremes",
            "Detect wick absorption — heavy tick volume in wicks without follow-through.",
            "M1",
            conditions=["Short above VAH/POC", "Long below VAL"],
        ),
        PlaybookStep(
            3,
            "Order Cluster Inversion",
            "Enter when price closes through nearby volume cluster (support/resistance flip).",
            "M1",
        ),
        PlaybookStep(
            4,
            "Risk Management",
            "SL beyond absorption wick; TP at VAL (short) or VWAP (long).",
            "M1",
        ),
    ]

    def on_start(self) -> None:
        self._session_date = None
        self._session_bars: list[Bar] = []
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None
        self._absorption_high: float | None = None
        self._absorption_low: float | None = None

    def _reset_session(self, ny_date) -> None:
        self._session_date = ny_date
        self._session_bars = []
        self._pending_short = None
        self._pending_long = None
        self._absorption_high = None
        self._absorption_low = None

    def _session_bars_for_today(
        self, history: Callable, current_time: datetime
    ) -> list[Bar]:
        ny = get_ny_time(current_time)
        if self._session_date != ny.date():
            self._reset_session(ny.date())

        m1_hist = history(self.symbol, TF.M1, 500)
        today_session = [
            b
            for b in m1_hist
            if get_ny_time(b.time).date() == ny.date() and is_in_session(b.time, "ny_am")
        ]
        self._session_bars = today_session
        return today_session

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if not m1:
            return []

        if not is_in_session(current_time, "ny_am"):
            return []

        session_bars = self._session_bars_for_today(history, current_time)
        if len(session_bars) < 20:
            return []

        vp = developing_vp(session_bars)
        if vp is None:
            return []

        vwap = session_vwap(session_bars)
        m1_hist = history(self.symbol, TF.M1, 30)

        # --- Short: buyer absorption at VAH / POC / VWAP ---
        at_premium = (
            near_level(m1.high, vp.vah)
            or near_level(m1.high, vp.poc)
            or near_level(m1.high, vwap)
        )
        if at_premium and detect_buyer_absorption(m1):
            support = find_support_cluster(m1_hist, lookback=12)
            if support is not None:
                self._pending_short = {
                    "cluster": support,
                    "absorption_high": m1.high,
                }
                self._absorption_high = m1.high

        if self._pending_short and m1.close < self._pending_short["cluster"]:
            entry = m1.close
            sl = self._pending_short["absorption_high"] + m1.total_range * 0.1
            risk = sl - entry
            if risk > 0:
                tp = entry - risk  # 1:1 to VAL area; cap at VAL if closer
                if vp.val < entry:
                    tp = max(vp.val, entry - risk)
                self._pending_short = None
                return [
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "short_vah_absorption", "target": "val"},
                    )
                ]

        # --- Long: seller absorption below VAL ---
        below_val = m1.close < vp.val or m1.low < vp.val
        if below_val and detect_seller_absorption(m1):
            resistance = find_resistance_cluster(m1_hist, lookback=12)
            if resistance is not None:
                self._pending_long = {
                    "cluster": resistance,
                    "absorption_low": m1.low,
                }
                self._absorption_low = m1.low

        if self._pending_long and m1.is_bullish and m1.close > self._pending_long["cluster"]:
            entry = m1.close
            sl = self._pending_long["absorption_low"] - m1.total_range * 0.1
            risk = entry - sl
            if risk > 0:
                tp = entry + risk * 2  # 1:2 toward VWAP per video example 2
                if vwap > entry:
                    tp = min(vwap, entry + risk * 2)
                self._pending_long = None
                return [
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "long_val_absorption", "target": "vwap"},
                    )
                ]

        return []
