"""
Video #1 — VP + Orderflow Absorption.

Fade failed aggressive orderflow at developing VP extremes after NY open.
Uses tick_volume in wicks as orderflow proxy (CSV has no L2 depth).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_after_ny_open
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    AbsorptionEvent,
    average_volume,
    compute_developing_vp,
    detect_buyer_absorption_at_highs,
    detect_seller_absorption_at_lows,
    near_level,
    recent_swing_high,
    recent_swing_low,
    vwap_from_bars,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Post-9:30 NY developing VP: fade buyer absorption at VAH/POC/VWAP "
        "and seller absorption below VAL using tick_volume wick proxy."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session VP from 9:30 NY; track POC, VAH, VAL, VWAP.",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption at Extremes",
            "Identify wick-heavy volume without follow-through at VAH (short) or VAL (long).",
            "M1",
        ),
        PlaybookStep(
            3,
            "Order Inversion",
            "Enter on close through nearby swing cluster after absorption.",
            "M1",
        ),
        PlaybookStep(
            4,
            "Risk",
            "SL beyond absorption wick; TP at VAL (short) or VWAP (long).",
            "M1",
        ),
    ]

    def on_start(self):
        self._session_date = None
        self._session_bars: list[Bar] = []
        self._pending_short: AbsorptionEvent | None = None
        self._pending_long: AbsorptionEvent | None = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if not m1:
            return []

        if not is_after_ny_open(current_time):
            return []

        ny_date = get_ny_time(current_time).date()
        if self._session_date != ny_date:
            self._session_date = ny_date
            self._session_bars = []
            self._pending_short = None
            self._pending_long = None

        self._session_bars.append(m1)
        if len(self._session_bars) < 30:
            return []

        vp = compute_developing_vp(self._session_bars)
        if not vp:
            return []

        vwap = vwap_from_bars(self._session_bars)
        hist = history(self.symbol, TF.M1, 30)
        avg_vol = average_volume(hist, lookback=20)
        signals: list[Signal] = []

        if detect_buyer_absorption_at_highs(m1, avg_vol):
            at_extreme = (
                near_level(m1.high, vp.vah)
                or near_level(m1.high, vp.poc)
                or (vwap is not None and near_level(m1.high, vwap))
            )
            if at_extreme and m1.high >= vp.vah * 0.999:
                swing_low = recent_swing_low(hist, lookback=6)
                if swing_low:
                    self._pending_short = AbsorptionEvent(
                        direction="buyer",
                        bar_index=len(self._session_bars) - 1,
                        cluster_low=swing_low,
                        cluster_high=m1.high,
                        wick_high=m1.high,
                        wick_low=m1.low,
                    )

        if self._pending_short and m1.close < self._pending_short.cluster_low:
            entry = m1.close
            sl = self._pending_short.wick_high + m1.total_range * 0.1
            tp = vp.val
            if sl > entry and tp < entry:
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

        if m1.close < vp.val and detect_seller_absorption_at_lows(m1, avg_vol):
            swing_high = recent_swing_high(hist, lookback=6)
            if swing_high:
                self._pending_long = AbsorptionEvent(
                    direction="seller",
                    bar_index=len(self._session_bars) - 1,
                    cluster_low=m1.low,
                    cluster_high=swing_high,
                    wick_high=m1.high,
                    wick_low=m1.low,
                )

        if self._pending_long and m1.close > self._pending_long.cluster_high:
            entry = m1.close
            sl = self._pending_long.wick_low - m1.total_range * 0.1
            tp = vwap if vwap else vp.poc
            if sl < entry and tp > entry:
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
