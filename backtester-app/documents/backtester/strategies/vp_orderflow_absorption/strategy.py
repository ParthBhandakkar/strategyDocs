"""
Video #1 — Orderflow and Volume Profile absorption at developing VP extremes.
Uses tick_volume wick concentration as orderflow proxy (no L2 data).
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import is_post_ny_open
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    compute_developing_vp,
    detect_wick_absorption,
    recent_swing_high,
    recent_swing_low,
    session_bars_since_ny_open,
    vwap_from_bars,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade failed auctions at developing daily VP extremes when aggressive "
        "volume concentrates in wicks without follow-through, then invert on close."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session VP/VWAP/POC after 9:30 NY open.",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Identify wick absorption at VAH/VAL/VWAP/POC extremes.",
            "M1",
        ),
        PlaybookStep(
            3,
            "Inversion Trigger",
            "Enter on close through local support/resistance cluster.",
            "M1",
        ),
    ]

    def on_start(self) -> None:
        self._pending_short_level: float | None = None
        self._pending_short_sl: float | None = None
        self._pending_long_level: float | None = None
        self._pending_long_sl: float | None = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if not m1 or not is_post_ny_open(current_time):
            return []

        hist = history(self.symbol, TF.M1, 500)
        if len(hist) < 20:
            return []

        session_bars = session_bars_since_ny_open(hist, len(hist) - 1)
        vp = compute_developing_vp(session_bars)
        if not vp:
            return []

        vwap = vwap_from_bars(session_bars)
        signals: list[Signal] = []

        near_upper = m1.high >= min(vp.vah, vp.poc) or (
            vwap is not None and m1.high >= vwap
        )
        near_lower = m1.low <= max(vp.val, vp.poc) or (
            vwap is not None and m1.low <= vwap
        )

        if near_upper and detect_wick_absorption(m1, "bearish"):
            swing = recent_swing_low(hist)
            if swing:
                self._pending_short_level = swing
                self._pending_short_sl = m1.high
                if self.step_tracker:
                    self.step_tracker.record(
                        "Buyer Absorption",
                        2,
                        current_time,
                        m1.high,
                        "M1",
                        "Absorption at upper VP extreme",
                    )

        if near_lower and detect_wick_absorption(m1, "bullish"):
            swing = recent_swing_high(hist)
            if swing:
                self._pending_long_level = swing
                self._pending_long_sl = m1.low
                if self.step_tracker:
                    self.step_tracker.record(
                        "Seller Absorption",
                        2,
                        current_time,
                        m1.low,
                        "M1",
                        "Absorption at lower VP extreme",
                    )

        if (
            self._pending_short_level is not None
            and self._pending_short_sl is not None
            and m1.is_bearish
            and m1.close < self._pending_short_level
        ):
            entry = m1.close
            sl = self._pending_short_sl
            risk = sl - entry
            if risk > 0:
                tp = entry - risk
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=max(tp, vp.val),
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vp_absorption_short", "target": "val"},
                    )
                )
            self._pending_short_level = None
            self._pending_short_sl = None

        if (
            self._pending_long_level is not None
            and self._pending_long_sl is not None
            and m1.is_bullish
            and m1.close > self._pending_long_level
        ):
            entry = m1.close
            sl = self._pending_long_sl
            risk = entry - sl
            if risk > 0:
                tp = entry + risk
                target = vwap if vwap else vp.poc
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=max(tp, target),
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vp_absorption_long", "target": "vwap"},
                    )
                )
            self._pending_long_level = None
            self._pending_long_sl = None

        return signals
