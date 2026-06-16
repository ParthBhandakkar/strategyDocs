"""
Video #1 — Orderflow and Volume Profile Day Trading Strategy.
Fade absorption at developing VP extremes when aggressive orders fail at wicks.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import is_post_ny_open, session_bars_since_ny_open
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    is_buyer_absorption,
    is_seller_absorption,
    nearest_support_cluster,
    nearest_resistance_cluster,
    price_near_level,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing daily VP extremes after NY open; "
        "enter on order-cluster inversion using tick-volume wick proxy."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session VP/VWAP from NY open M1 bars.",
            "M1",
            ["Post 09:30 NY"],
            ["POC", "VAH", "VAL", "VWAP"],
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Detect buyer/seller absorption at VP extremes via wick volume.",
            "M1",
            ["Wick volume > body volume"],
            ["VAH", "VAL"],
        ),
        PlaybookStep(
            3,
            "Cluster Inversion",
            "Enter when price closes through nearby order cluster.",
            "M1",
            ["Close below support for shorts", "Close above resistance for longs"],
            [],
        ),
    ]

    def on_start(self):
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None
        self._last_session_day = None

    def on_bar(self, bars, history, multi_symbol_bars, current_time: datetime) -> list[Signal]:
        if not is_post_ny_open(current_time):
            return []

        m1_bar = bars.get(TF.M1)
        if not m1_bar:
            return []

        m1_hist = history(self.symbol, TF.M1, 500)
        session_bars = session_bars_since_ny_open(m1_hist, current_time)
        if len(session_bars) < 30:
            return []

        ny_day = current_time.date()
        if self._last_session_day != ny_day:
            self._pending_short = None
            self._pending_long = None
            self._last_session_day = ny_day

        profile = compute_frvp(session_bars)
        if profile is None:
            return []

        signals: list[Signal] = []

        if self._pending_short:
            cluster = self._pending_short["cluster"]
            if m1_bar.close < cluster:
                entry = m1_bar.close
                stop = self._pending_short["stop"]
                target = profile.val
                risk = stop - entry
                if risk > 0 and target < entry:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=entry,
                            stop_loss=stop,
                            take_profit=target,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "short_absorption_vah"},
                        )
                    )
                self._pending_short = None

        if self._pending_long:
            cluster = self._pending_long["cluster"]
            if m1_bar.close > cluster:
                entry = m1_bar.close
                stop = self._pending_long["stop"]
                target = profile.vwap
                risk = entry - stop
                if risk > 0 and target > entry:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=entry,
                            stop_loss=stop,
                            take_profit=target,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "long_absorption_val"},
                        )
                    )
                self._pending_long = None

        if signals:
            return signals

        key_levels = [profile.vah, profile.poc, profile.vwap]
        at_premium = any(price_near_level(m1_bar.high, lvl) for lvl in key_levels)
        at_discount = m1_bar.low < profile.val

        if at_premium and is_buyer_absorption(m1_bar):
            cluster = nearest_support_cluster(session_bars)
            if cluster is not None and m1_bar.close >= cluster:
                self._pending_short = {
                    "cluster": cluster,
                    "stop": m1_bar.high,
                }
                if self.step_tracker:
                    self.step_tracker.record(
                        "Buyer Absorption",
                        2,
                        current_time,
                        m1_bar.high,
                        "M1",
                        f"Absorption near VAH/POC; watch break below {cluster:.5f}",
                    )

        if at_discount and is_seller_absorption(m1_bar):
            cluster = nearest_resistance_cluster(session_bars)
            if cluster is not None and m1_bar.close <= cluster:
                self._pending_long = {
                    "cluster": cluster,
                    "stop": m1_bar.low,
                }
                if self.step_tracker:
                    self.step_tracker.record(
                        "Seller Absorption",
                        2,
                        current_time,
                        m1_bar.low,
                        "M1",
                        f"Absorption below VAL; watch break above {cluster:.5f}",
                    )

        return []
