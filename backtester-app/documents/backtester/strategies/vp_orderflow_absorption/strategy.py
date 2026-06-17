"""
Video #1: Orderflow and Volume Profile Day Trading Strategy.
Fade absorption at developing VP extremes when order clusters fail at wicks.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import is_post_ny_open, session_bars_since_ny_open
from backtester.indicators.volume_profile import compute_frvp
from backtester.indicators.orderflow import (
    _avg_volume,
    detect_wick_absorption,
    find_order_cluster,
    vwap_from_bars,
)
from backtester.strategies.base import BaseStrategy


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Post-9:30 NY developing VP: fade buyer absorption at VAH/POC and "
        "seller absorption below VAL when price inverts local order clusters."
    )
    timeframes = [TF.M1, TF.D1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session VP from 9:30 NY M1 bars; track POC, VAH, VAL, VWAP.",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption at Extremes",
            "Detect wick volume absorption near VAH (short) or below VAL (long).",
            "M1",
        ),
        PlaybookStep(
            3,
            "Order Cluster Inversion",
            "Enter on close through nearby order cluster after absorption.",
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
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None
        self._last_session_date = None

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

        m1_hist = history(self.symbol, TF.M1, 500)
        session_bars = session_bars_since_ny_open(m1_hist, current_time)
        if len(session_bars) < 30:
            return []

        vp = compute_frvp(session_bars)
        if not vp:
            return []

        vwap = vwap_from_bars(session_bars)
        avg_vol = _avg_volume(m1_hist)
        absorption = detect_wick_absorption(m1_bar, avg_vol, min_vol_ratio=1.5)
        cluster = find_order_cluster(m1_hist, lookback=5)
        if not cluster:
            return []
        cluster_low, cluster_high = cluster
        tol = m1_bar.close * 0.0015

        signals: list[Signal] = []

        near_vah = abs(m1_bar.high - vp.vah) <= tol or abs(m1_bar.close - vp.poc) <= tol
        below_val = m1_bar.close < vp.val

        if absorption == "buyer" and near_vah:
            self._pending_short = {
                "absorption_high": m1_bar.high,
                "cluster_low": cluster_low,
                "target": vp.val,
            }

        if absorption == "seller" and below_val:
            self._pending_long = {
                "absorption_low": m1_bar.low,
                "cluster_high": cluster_high,
                "target": vwap,
            }

        if self._pending_short and m1_bar.close < self._pending_short["cluster_low"]:
            entry = m1_bar.close
            sl = self._pending_short["absorption_high"] + tol
            tp = self._pending_short["target"]
            if sl > entry > tp:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vah_buyer_absorption"},
                    )
                )
            self._pending_short = None

        if self._pending_long and m1_bar.close > self._pending_long["cluster_high"]:
            entry = m1_bar.close
            sl = self._pending_long["absorption_low"] - tol
            tp = self._pending_long["target"]
            if sl < entry < tp:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "val_seller_absorption"},
                    )
                )
            self._pending_long = None

        return signals
