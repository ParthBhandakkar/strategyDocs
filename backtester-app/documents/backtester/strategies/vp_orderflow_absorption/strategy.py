"""
Video #1 — VP + Orderflow Absorption at developing VP extremes.
Approximates L2 absorption using tick_volume wick patterns on M1.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Direction, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_post_ny_open
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    detect_buyer_absorption,
    detect_seller_absorption,
    developing_vp,
    recent_swing_high,
    recent_swing_low,
    session_bars_for_day,
    vwap_from_bars,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes after NY open: "
        "short above VAH on buyer wick absorption + cluster break; "
        "long below VAL on seller wick absorption + reclaim."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP",
            description="Build session VP from NY 9:30 M1 bars",
            timeframe="M1",
            conditions=["Post 9:30 NY", "Minimum 20 session bars"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption",
            description="Detect wick absorption at VAH (short) or VAL (long)",
            timeframe="M1",
            conditions=["Volume spike in wick", "No follow-through"],
        ),
        PlaybookStep(
            step_number=3,
            title="Trigger",
            description="Close beyond local order cluster / swing",
            timeframe="M1",
            conditions=["Bearish close below cluster for short", "Bullish close above cluster for long"],
        ),
    ]

    def on_start(self):
        self._pending_short_cluster: float | None = None
        self._pending_short_sl: float | None = None
        self._pending_long_cluster: float | None = None
        self._pending_long_sl: float | None = None
        self._last_ny_day = None

    def on_bar(self, bars, history, multi_symbol_bars, current_time):
        if TF.M1 not in bars:
            return []

        bar: Bar = bars[TF.M1]
        if not is_post_ny_open(current_time):
            return []

        ny_day = get_ny_time(current_time).date()
        if self._last_ny_day != ny_day:
            self._pending_short_cluster = None
            self._pending_short_sl = None
            self._pending_long_cluster = None
            self._pending_long_sl = None
            self._last_ny_day = ny_day

        m1_hist = history(None, TF.M1, 500)
        session = session_bars_for_day(m1_hist, ny_day)
        if len(session) < 20:
            return []

        vp = developing_vp(session)
        if vp is None:
            return []

        vwap = vwap_from_bars(session)
        recent = session[-30:]
        avg_vol = sum(b.tick_volume or 1 for b in recent) / len(recent)
        signals: list[Signal] = []

        # Short setup: at/above VAH with buyer absorption
        if bar.high >= vp.vah * 0.9995 and detect_buyer_absorption(bar, avg_vol):
            cluster = recent_swing_low(recent, lookback=6)
            if cluster is not None:
                self._pending_short_cluster = cluster
                self._pending_short_sl = bar.high

        if (
            self._pending_short_cluster is not None
            and self._pending_short_sl is not None
            and bar.is_bearish
            and bar.close < self._pending_short_cluster
        ):
            entry = bar.close
            sl = self._pending_short_sl
            risk = sl - entry
            if risk > 0:
                tp = max(vp.val, entry - risk)
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
            self._pending_short_cluster = None
            self._pending_short_sl = None

        # Long setup: at/below VAL with seller absorption
        if bar.low <= vp.val * 1.0005 and detect_seller_absorption(bar, avg_vol):
            cluster = recent_swing_high(recent, lookback=6)
            if cluster is not None:
                self._pending_long_cluster = cluster
                self._pending_long_sl = bar.low

        if (
            self._pending_long_cluster is not None
            and self._pending_long_sl is not None
            and bar.is_bullish
            and bar.close > self._pending_long_cluster
        ):
            entry = bar.close
            sl = self._pending_long_sl
            risk = entry - sl
            if risk > 0:
                tp = min(vwap, entry + risk * 2)
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
            self._pending_long_cluster = None
            self._pending_long_sl = None

        return signals
