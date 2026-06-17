"""Video #1 — VP + orderflow absorption."""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Direction, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.volume_profile import compute_frvp, compute_session_vwap
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    detect_buyer_absorption,
    detect_seller_absorption,
    find_support_cluster,
    near_level,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade failed absorption at developing NY session volume profile extremes; "
        "enter on order-cluster inversion after wick absorption."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session VP/VWAP after 9:30 NY open.",
            "M1",
            conditions=["Post 9:30 NY", "Track POC/VAH/VAL/VWAP"],
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Identify wick absorption at VAH (short) or VAL (long).",
            "M1",
            conditions=["High tick_volume in wick", "No follow-through"],
        ),
        PlaybookStep(
            3,
            "Cluster Inversion",
            "Enter when price closes through nearby order cluster.",
            "M1",
            conditions=["Short below support cluster", "Long above sell cluster"],
        ),
    ]

    def on_start(self) -> None:
        self._session_date = None
        self._buyer_absorption_high = None
        self._seller_absorption_low = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        m1_bar = bars.get(TF.M1)
        if m1_bar is None:
            return []

        if not is_in_session(current_time, "ny_am"):
            return []

        ny_time = get_ny_time(current_time)
        session_date = ny_time.date()
        if self._session_date != session_date:
            self._session_date = session_date
            self._buyer_absorption_high = None
            self._seller_absorption_low = None

        m1_hist = history(self.symbol, TF.M1, 500)
        session_bars = [
            bar
            for bar in m1_hist
            if get_ny_time(bar.time).date() == session_date and is_in_session(bar.time, "ny_am")
        ]
        if len(session_bars) < 20:
            return []

        profile = compute_frvp(session_bars, row_size=80, va_pct=70.0)
        if profile is None:
            return []

        vwap = compute_session_vwap(session_bars)
        if vwap is None:
            return []

        avg_volume = sum(bar.tick_volume or 1 for bar in session_bars[-20:]) / 20.0

        if detect_buyer_absorption(m1_bar, avg_volume) and (
            near_level(m1_bar.high, profile.vah, tolerance_pct=0.002)
            or near_level(m1_bar.high, profile.poc, tolerance_pct=0.002)
            or near_level(m1_bar.high, vwap, tolerance_pct=0.002)
        ):
            self._buyer_absorption_high = m1_bar.high
            if self.step_tracker:
                self.step_tracker.record(
                    "Buyer Absorption",
                    2,
                    current_time,
                    m1_bar.high,
                    "M1",
                    "Buyer absorption at VP upper extreme",
                )

        if detect_seller_absorption(m1_bar, avg_volume) and (
            near_level(m1_bar.low, profile.val, tolerance_pct=0.002)
            or m1_bar.close < profile.val
        ):
            self._seller_absorption_low = m1_bar.low
            if self.step_tracker:
                self.step_tracker.record(
                    "Seller Absorption",
                    2,
                    current_time,
                    m1_bar.low,
                    "M1",
                    "Seller absorption below VAL",
                )

        signals: list[Signal] = []

        support_cluster = find_support_cluster(session_bars)
        if (
            self._buyer_absorption_high is not None
            and support_cluster is not None
            and m1_bar.is_bearish
            and m1_bar.close < support_cluster.level
        ):
            stop_loss = self._buyer_absorption_high + (m1_bar.high - m1_bar.low) * 0.1
            risk = stop_loss - m1_bar.close
            if risk > 0:
                take_profit = m1_bar.close - risk
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=m1_bar.close,
                        stop_loss=stop_loss,
                        take_profit=max(take_profit, profile.val),
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={
                            "setup": "vp_absorption_short",
                            "cluster_level": support_cluster.level,
                            "vah": profile.vah,
                            "val": profile.val,
                            "poc": profile.poc,
                        },
                    )
                )
                self._buyer_absorption_high = None

        resistance_cluster = find_resistance_cluster(session_bars)
        if (
            self._seller_absorption_low is not None
            and resistance_cluster is not None
            and m1_bar.is_bullish
            and m1_bar.close > resistance_cluster.level
        ):
            stop_loss = self._seller_absorption_low - (m1_bar.high - m1_bar.low) * 0.1
            risk = m1_bar.close - stop_loss
            if risk > 0:
                take_profit = m1_bar.close + risk * 2.0
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=m1_bar.close,
                        stop_loss=stop_loss,
                        take_profit=min(take_profit, vwap),
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={
                            "setup": "vp_absorption_long",
                            "cluster_level": resistance_cluster.level,
                            "vah": profile.vah,
                            "val": profile.val,
                            "poc": profile.poc,
                        },
                    )
                )
                self._seller_absorption_low = None

        return signals
