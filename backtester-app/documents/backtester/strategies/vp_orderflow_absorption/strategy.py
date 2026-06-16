"""
VP + Orderflow Absorption — fade failed aggression at developing VP extremes.
Video #1 canonical module (cluster A).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.strategies.base import BaseStrategy
from backtester.indicators.sessions import is_post_ny_open, ny_session_date
from backtester.indicators.volume_profile import compute_frvp
from backtester.indicators.orderflow import (
    detect_buyer_absorption,
    detect_seller_absorption,
    compute_session_vwap,
    recent_support_cluster,
    recent_resistance_cluster,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Post 9:30 NY fade: buyer absorption at VAH/POC/VWAP with bearish cluster break; "
        "seller absorption below VAL with bullish cluster reclaim."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session volume profile and VWAP after 9:30 NY open.",
            "M1",
            ["Post 9:30 NY"],
            ["POC", "VAH", "VAL", "VWAP"],
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Identify tick_volume spike in wick without follow-through at VP extreme.",
            "M1",
            ["Upper wick buyer absorption at VAH", "Lower wick seller absorption at VAL"],
            ["VAH", "VAL"],
        ),
        PlaybookStep(
            3,
            "Inversion Entry",
            "Enter on close through close-proximity order cluster after absorption.",
            "M1",
            ["Short below support cluster", "Long above resistance cluster"],
            ["Cluster level", "Absorption wick"],
        ),
    ]

    MIN_VOLUME = 60
    MIN_WICK_RATIO = 0.40
    CLUSTER_LOOKBACK = 5
    VP_LOOKBACK = 120

    def on_start(self):
        self._session_day = None
        self._session_bars: list[Bar] = []
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        if TF.M1 not in bars:
            return []

        if not is_post_ny_open(current_time):
            return []

        bar = bars[TF.M1]
        m1_hist = history(None, TF.M1, self.VP_LOOKBACK + 10)
        if len(m1_hist) < 20:
            return []

        session_day = ny_session_date(current_time)
        if self._session_day != session_day:
            self._session_day = session_day
            self._session_bars = []
            self._pending_short = None
            self._pending_long = None

        self._session_bars.append(bar)
        if len(self._session_bars) < 15:
            return []

        vp = compute_frvp(self._session_bars)
        if vp is None:
            return []

        vwap = compute_session_vwap(self._session_bars)
        signals: list[Signal] = []

        near_vah = bar.high >= vp.vah * 0.9995 or abs(bar.close - vp.vah) / vp.vah < 0.001
        near_val = bar.low <= vp.val * 1.0005 or abs(bar.close - vp.val) / max(vp.val, 1e-9) < 0.001
        near_poc_vwap = (
            abs(bar.close - vp.poc) / max(vp.poc, 1e-9) < 0.0015
            or abs(bar.close - vwap) / max(vwap, 1e-9) < 0.0015
        )

        if detect_buyer_absorption(bar, self.MIN_WICK_RATIO, self.MIN_VOLUME):
            if near_vah or (near_poc_vwap and bar.close >= vp.poc):
                cluster = recent_support_cluster(m1_hist[:-1], self.CLUSTER_LOOKBACK)
                self._pending_short = {
                    "cluster": cluster,
                    "wick_high": bar.high,
                    "val_target": vp.val,
                }

        if detect_seller_absorption(bar, self.MIN_WICK_RATIO, self.MIN_VOLUME):
            if near_val or (near_poc_vwap and bar.close <= vp.poc):
                cluster = recent_resistance_cluster(m1_hist[:-1], self.CLUSTER_LOOKBACK)
                self._pending_long = {
                    "cluster": cluster,
                    "wick_low": bar.low,
                    "vwap_target": vwap,
                }

        if self._pending_short and bar.close < self._pending_short["cluster"]:
            entry = bar.close
            sl = self._pending_short["wick_high"]
            tp = self._pending_short["val_target"]
            if entry < sl and entry > tp:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "buyer_absorption_vah", "session": str(session_day)},
                    )
                )
            self._pending_short = None

        if self._pending_long and bar.close > self._pending_long["cluster"]:
            entry = bar.close
            sl = self._pending_long["wick_low"]
            tp = self._pending_long["vwap_target"]
            if entry > sl and entry < tp:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "seller_absorption_val", "session": str(session_day)},
                    )
                )
            self._pending_long = None

        return signals
