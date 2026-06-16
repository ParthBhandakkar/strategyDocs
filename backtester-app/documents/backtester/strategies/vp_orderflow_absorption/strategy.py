"""
Video #1: VP + Orderflow Absorption
Fade absorption at developing VP extremes when aggressive flow fails at wicks
and price inverts local order clusters.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_session_bars_for_day, is_post_ny_open
from backtester.indicators.volume_profile import compute_frvp, near_level
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    average_volume,
    detect_lower_wick_absorption,
    detect_upper_wick_absorption,
    find_resistance_cluster,
    find_support_cluster,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Developing NY session volume profile with tick-volume absorption proxy "
        "at VAH/VWAP/POC (short) and VAL (long), confirmed by order-cluster inversion."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session VP from 9:30 NY open (VWAP, POC, VAH, VAL).",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Identify wick absorption at VP extremes using tick volume proxy.",
            "M1",
        ),
        PlaybookStep(
            3,
            "Cluster Inversion",
            "Enter on close through local support/resistance cluster.",
            "M1",
        ),
        PlaybookStep(
            4,
            "Targets",
            "Short targets VAL; long targets VWAP with 1:1 minimum RR.",
            "M1",
        ),
    ]

    def on_start(self):
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None
        self._last_trade_day: str | None = None
        self._min_wick_ratio = 0.35
        self._min_volume_ratio = 1.2
        self._cluster_lookback = 8

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

        if not is_post_ny_open(current_time):
            return []

        hist = history(self.symbol, TF.M1, 500)
        if len(hist) < 30:
            return []

        session_bars = get_session_bars_for_day(hist, current_time)
        if len(session_bars) < 20:
            return []

        profile = compute_frvp(session_bars)
        if profile is None:
            return []

        avg_vol = average_volume(hist[:-1])
        support_cluster = find_support_cluster(hist[:-1], self._cluster_lookback)
        resistance_cluster = find_resistance_cluster(hist[:-1], self._cluster_lookback)

        signals: list[Signal] = []

        at_premium = (
            near_level(m1_bar.high, profile.vah)
            or near_level(m1_bar.high, profile.poc)
            or near_level(m1_bar.high, profile.vwap)
        )
        at_discount = near_level(m1_bar.low, profile.val) or m1_bar.close < profile.val

        if at_premium and detect_upper_wick_absorption(
            m1_bar, avg_vol, self._min_wick_ratio, self._min_volume_ratio
        ):
            self._pending_short = {
                "absorption_high": m1_bar.high,
                "cluster": support_cluster,
            }
            if self.step_tracker:
                self.step_tracker.record(
                    "Buyer Absorption",
                    2,
                    current_time,
                    m1_bar.high,
                    "M1",
                    f"Upper wick absorption near VAH/POC/VWAP at {m1_bar.high:.5f}",
                )

        if at_discount and detect_lower_wick_absorption(
            m1_bar, avg_vol, self._min_wick_ratio, self._min_volume_ratio
        ):
            self._pending_long = {
                "absorption_low": m1_bar.low,
                "cluster": resistance_cluster,
            }
            if self.step_tracker:
                self.step_tracker.record(
                    "Seller Absorption",
                    2,
                    current_time,
                    m1_bar.low,
                    "M1",
                    f"Lower wick absorption below VAL at {m1_bar.low:.5f}",
                )

        if self._pending_short and support_cluster is not None:
            cluster = self._pending_short.get("cluster") or support_cluster
            if m1_bar.close < cluster:
                stop = float(self._pending_short["absorption_high"])
                entry = m1_bar.close
                risk = stop - entry
                if risk > 0:
                    tp = max(profile.val, entry - risk)
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=entry,
                            stop_loss=stop,
                            take_profit=tp,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "vp_absorption_short"},
                        )
                    )
                self._pending_short = None

        if self._pending_long and resistance_cluster is not None:
            cluster = self._pending_long.get("cluster") or resistance_cluster
            if m1_bar.close > cluster:
                stop = float(self._pending_long["absorption_low"])
                entry = m1_bar.close
                risk = entry - stop
                if risk > 0:
                    tp = max(entry + risk, profile.vwap)
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=entry,
                            stop_loss=stop,
                            take_profit=tp,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "vp_absorption_long"},
                        )
                    )
                self._pending_long = None

        return signals
