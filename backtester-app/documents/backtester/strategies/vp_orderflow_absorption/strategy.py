"""VP + Orderflow Absorption strategy (Video #1, Cluster A)."""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, Direction
from backtester.core.timeframes import TF
from backtester.core import PlaybookStep
from backtester.strategies.base import BaseStrategy
from backtester.indicators.sessions import is_in_session
from backtester.strategies.vp_orderflow_absorption.helpers import (
    developing_session_vp,
    detect_buyer_absorption,
    detect_seller_absorption,
    local_support_cluster,
    local_resistance_cluster,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade failed absorption at developing session VP extremes after NY open. "
        "Proxy orderflow via tick-volume wick absorption; enter on cluster inversion."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Session VP",
            "Build developing VP from M1 bars since 9:30 NY",
            "M1",
            ["Post 9:30 NY"],
            ["POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Identify wick absorption at VAH (short) or VAL (long)",
            "M1",
            ["High tick volume in wick without follow-through"],
            ["VAH", "VAL"],
        ),
        PlaybookStep(
            3,
            "Trigger",
            "Enter on close through local order cluster (support/resistance proxy)",
            "M1",
            ["Close below support cluster (short)", "Close above resistance cluster (long)"],
            [],
        ),
    ]

    CLUSTER_LOOKBACK = 20
    MIN_ABSORPTION_RATIO = 1.5
    MIN_RR = 1.0

    def on_start(self):
        self._last_signal_bar: datetime | None = None

    def on_bar(self, bars, history, multi_symbol_bars, current_time):
        m1 = bars.get(TF.M1)
        if m1 is None:
            return []

        if not is_in_session(current_time, "new_york"):
            return []

        hist = history(None, TF.M1, 500)
        if len(hist) < 50:
            return []

        if self._last_signal_bar == m1.time:
            return []

        vp = developing_session_vp(hist, current_time)
        if vp is None:
            return []

        signals: list[Signal] = []
        support = local_support_cluster(hist[:-1], self.CLUSTER_LOOKBACK)
        resistance = local_resistance_cluster(hist[:-1], self.CLUSTER_LOOKBACK)

        prev = hist[-2] if len(hist) >= 2 else None

        # Short: buyer absorption near/above VAH, close below support cluster
        if prev and detect_buyer_absorption(prev, self.MIN_ABSORPTION_RATIO):
            near_vah = prev.high >= vp.vah * 0.9995
            if near_vah and m1.close < support and m1.is_bearish:
                sl = prev.high + m1.total_range * 0.1
                risk = sl - m1.close
                tp = m1.close - risk * self.MIN_RR
                if risk > 0 and tp < m1.close:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=m1.close,
                            stop_loss=sl,
                            take_profit=max(tp, vp.val),
                            timestamp=m1.time,
                            symbol=self.symbol,
                            metadata={"setup": "vah_buyer_absorption", "vah": vp.vah},
                        )
                    )

        # Long: seller absorption below VAL, close above resistance cluster
        if prev and detect_seller_absorption(prev, self.MIN_ABSORPTION_RATIO):
            below_val = prev.low <= vp.val * 1.0005
            if below_val and m1.close > resistance and m1.is_bullish:
                sl = prev.low - m1.total_range * 0.1
                risk = m1.close - sl
                tp = m1.close + risk * self.MIN_RR * 2
                if risk > 0 and tp > m1.close:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=m1.close,
                            stop_loss=sl,
                            take_profit=min(tp, vp.poc + (vp.vah - vp.poc)),
                            timestamp=m1.time,
                            symbol=self.symbol,
                            metadata={"setup": "val_seller_absorption", "val": vp.val},
                        )
                    )

        if signals:
            self._last_signal_bar = m1.time
        return signals
