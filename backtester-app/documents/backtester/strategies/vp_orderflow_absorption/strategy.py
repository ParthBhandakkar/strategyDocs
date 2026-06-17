"""VP + Orderflow Absorption strategy (Video #1)."""

from __future__ import annotations

from datetime import datetime

from backtester.core import Direction, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    detect_buyer_absorption,
    detect_seller_absorption,
    is_post_ny_open,
    recent_resistance_cluster,
    recent_support_cluster,
    session_bars_since_ny_open,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing daily VP extremes after NY open. "
        "Short failed buyer absorption above VAH; long seller absorption below VAL."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session volume profile from post-9:30 NY M1 bars.",
            "M1",
            ["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Identify wick-heavy tick volume without follow-through at VA extremes.",
            "M1",
            ["Upper wick buyer absorption", "Lower wick seller absorption"],
        ),
        PlaybookStep(
            3,
            "Order inversion",
            "Enter on close through local support/resistance cluster.",
            "M1",
            ["Close below support for short", "Close above resistance for long"],
        ),
    ]

    VOLUME_THRESHOLD = 50
    CLUSTER_LOOKBACK = 8

    def on_start(self):
        self._pending_short_absorption: dict | None = None
        self._pending_long_absorption: dict | None = None

    def on_bar(
        self,
        bars: dict[TF, object],
        history,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1_bar = bars.get(TF.M1)
        if m1_bar is None or not is_post_ny_open(current_time):
            return []

        m1_hist = history(self.symbol, TF.M1, 500)
        session_bars = session_bars_since_ny_open(m1_hist, current_time)
        if len(session_bars) < 30:
            return []

        profile = compute_frvp(session_bars, row_size=60)
        if profile is None:
            return []

        signals: list[Signal] = []

        if detect_buyer_absorption(m1_bar, self.VOLUME_THRESHOLD):
            if m1_bar.high >= profile.vah * 0.999:
                self._pending_short_absorption = {
                    "wick_high": m1_bar.high,
                    "cluster": recent_support_cluster(m1_hist[:-1], self.CLUSTER_LOOKBACK),
                }

        if self._pending_short_absorption:
            cluster = self._pending_short_absorption["cluster"]
            wick_high = self._pending_short_absorption["wick_high"]
            if cluster > 0 and m1_bar.close < cluster and m1_bar.is_bearish:
                stop = wick_high + (wick_high - m1_bar.close) * 0.1
                risk = stop - m1_bar.close
                if risk > 0:
                    take_profit = max(profile.val, m1_bar.close - risk)
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=m1_bar.close,
                            stop_loss=stop,
                            take_profit=take_profit,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "vah_absorption_short"},
                        )
                    )
                self._pending_short_absorption = None

        if detect_seller_absorption(m1_bar, self.VOLUME_THRESHOLD):
            if m1_bar.low <= profile.val * 1.001:
                self._pending_long_absorption = {
                    "wick_low": m1_bar.low,
                    "cluster": recent_resistance_cluster(m1_hist[:-1], self.CLUSTER_LOOKBACK),
                }

        if self._pending_long_absorption:
            cluster = self._pending_long_absorption["cluster"]
            wick_low = self._pending_long_absorption["wick_low"]
            if cluster > 0 and m1_bar.close > cluster and m1_bar.is_bullish:
                stop = wick_low - (m1_bar.close - wick_low) * 0.1
                risk = m1_bar.close - stop
                if risk > 0:
                    take_profit = min(profile.vwap or profile.poc, m1_bar.close + risk * 2)
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=m1_bar.close,
                            stop_loss=stop,
                            take_profit=take_profit,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "val_absorption_long"},
                        )
                    )
                self._pending_long_absorption = None

        return signals
