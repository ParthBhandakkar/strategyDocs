"""
Video #1 — VP + Orderflow Absorption at developing session extremes.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Direction, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.orderflow import (
    detect_buyer_absorption,
    detect_seller_absorption,
    find_local_resistance_cluster,
    find_local_support_cluster,
)
from backtester.indicators.sessions import is_post_ny_open, session_bars_since_ny_open
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import developing_session_profile


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
            step_number=1,
            title="Developing session VP",
            description="Build session volume profile from 9:30 NY M1 bars.",
            timeframe="M1",
            conditions=["Post 9:30 NY", "Minimum session bars accumulated"],
            key_levels=["VWAP/POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption at extremes",
            description="Detect buyer absorption above VAH/POC or seller absorption below VAL.",
            timeframe="M1",
            conditions=["Wick volume concentration", "No follow-through"],
        ),
        PlaybookStep(
            step_number=3,
            title="Cluster inversion entry",
            description="Enter when price closes through local order cluster in fade direction.",
            timeframe="M1",
            conditions=["Close below support cluster for shorts", "Close above resistance cluster for longs"],
        ),
    ]

    def on_start(self):
        self.absorption_min_ratio = 1.5
        self.cluster_lookback = 8
        self.min_session_bars = 30
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None

    def on_bar(self, bars, history, multi_symbol_bars, current_time):
        if TF.M1 not in bars:
            return []

        if not is_post_ny_open(current_time):
            self._pending_short = None
            self._pending_long = None
            return []

        m1_history = history(None, TF.M1, 400)
        session_bars = session_bars_since_ny_open(m1_history, current_time)
        if len(session_bars) < self.min_session_bars:
            return []

        profile = developing_session_profile(session_bars)
        if profile is None:
            return []

        bar = bars[TF.M1]
        signals: list[Signal] = []

        near_vah = bar.high >= profile.vah * 0.9995
        below_val = bar.close <= profile.val * 1.0005

        if near_vah and detect_buyer_absorption(bar, self.absorption_min_ratio):
            cluster_low, cluster_high = find_local_support_cluster(
                session_bars[:-1], self.cluster_lookback
            )
            self._pending_short = {
                "cluster_high": cluster_high,
                "absorption_high": bar.high,
                "target": profile.val,
            }

        if below_val and detect_seller_absorption(bar, self.absorption_min_ratio):
            cluster_low, cluster_high = find_local_resistance_cluster(
                session_bars[:-1], self.cluster_lookback
            )
            self._pending_long = {
                "cluster_low": cluster_low,
                "absorption_low": bar.low,
                "target": profile.poc,
            }

        if self._pending_short and bar.close < self._pending_short["cluster_high"]:
            stop = self._pending_short["absorption_high"]
            entry = bar.close
            target = self._pending_short["target"]
            risk = stop - entry
            if risk > 0:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=entry - risk,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vah_buyer_absorption_fade"},
                    )
                )
            self._pending_short = None

        if self._pending_long and bar.close > self._pending_long["cluster_low"]:
            stop = self._pending_long["absorption_low"]
            entry = bar.close
            risk = entry - stop
            if risk > 0:
                reward = max(self._pending_long["target"] - entry, risk)
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=entry + reward,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "val_seller_absorption_reversal"},
                    )
                )
            self._pending_long = None

        return signals
