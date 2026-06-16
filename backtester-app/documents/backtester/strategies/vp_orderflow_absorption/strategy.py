"""
Video #1 — Orderflow and Volume Profile Day Trading Strategy.
Fade absorption at developing VP extremes after NY open.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import is_in_session, session_bars_since_ny_open
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    AbsorptionEvent,
    is_buyer_absorption,
    is_seller_absorption,
    near_level,
    volume_threshold_from_history,
)


class VPOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade failed aggressive orderflow at developing NY session volume profile extremes. "
        "Short buyer absorption above VAH/POC/VWAP; long seller absorption below VAL."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session volume profile from 09:30 NY using M1 bars.",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption at Extremes",
            "Identify wick absorption at VAH/POC/VWAP (short) or VAL (long).",
            "M1",
        ),
        PlaybookStep(
            3,
            "Order Inversion",
            "Enter when price closes through the local absorbed order cluster.",
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
        self.min_volume_percentile = 70
        self.vp_touch_tolerance_pct = 0.0015
        self.min_wick_body_ratio = 1.5
        self.local_support_lookback = 8
        self._pending_short: AbsorptionEvent | None = None
        self._pending_long: AbsorptionEvent | None = None
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

        if not is_in_session(current_time, "ny_am") and not is_in_session(current_time, "ny_pm"):
            return []

        m1_hist = history(self.symbol, TF.M1, 500)
        if len(m1_hist) < 30:
            return []

        session_bars = session_bars_since_ny_open(m1_hist, current_time)
        if len(session_bars) < 20:
            return []

        session_date = session_bars[0].time.date()
        if self._last_session_date != session_date:
            self._pending_short = None
            self._pending_long = None
            self._last_session_date = session_date

        vp = compute_frvp(session_bars, row_size=80, va_pct=70.0)
        if not vp:
            return []

        vol_threshold = volume_threshold_from_history(session_bars, self.min_volume_percentile)
        signals: list[Signal] = []

        at_upper_extreme = (
            near_level(m1_bar.high, vp.vah, self.vp_touch_tolerance_pct)
            or near_level(m1_bar.high, vp.poc, self.vp_touch_tolerance_pct)
            or near_level(m1_bar.high, vp.vwap, self.vp_touch_tolerance_pct)
        )
        at_lower_extreme = near_level(m1_bar.low, vp.val, self.vp_touch_tolerance_pct)

        if at_upper_extreme and is_buyer_absorption(
            m1_bar, self.min_wick_body_ratio, vol_threshold
        ):
            local_low = min(
                bar.low for bar in session_bars[-self.local_support_lookback :]
            )
            self._pending_short = AbsorptionEvent(
                direction="short",
                level=local_low,
                wick_extreme=m1_bar.high,
                bar_time=m1_bar.time.isoformat(),
            )
            if self.step_tracker:
                self.step_tracker.record(
                    "Buyer Absorption",
                    2,
                    current_time,
                    m1_bar.high,
                    "M1",
                    f"Absorption near VAH/POC/VWAP at {m1_bar.high:.5f}",
                )

        if at_lower_extreme and is_seller_absorption(
            m1_bar, self.min_wick_body_ratio, vol_threshold
        ):
            local_high = max(
                bar.high for bar in session_bars[-self.local_support_lookback :]
            )
            self._pending_long = AbsorptionEvent(
                direction="long",
                level=local_high,
                wick_extreme=m1_bar.low,
                bar_time=m1_bar.time.isoformat(),
            )
            if self.step_tracker:
                self.step_tracker.record(
                    "Seller Absorption",
                    2,
                    current_time,
                    m1_bar.low,
                    "M1",
                    f"Absorption below VAL at {m1_bar.low:.5f}",
                )

        if self._pending_short and m1_bar.close < self._pending_short.level:
            stop = self._pending_short.wick_extreme
            risk = stop - m1_bar.close
            if risk > 0 and vp.val < m1_bar.close:
                take_profit = vp.val
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=m1_bar.close,
                        stop_loss=stop,
                        take_profit=take_profit,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vp_absorption_short", "target": "val"},
                    )
                )
            self._pending_short = None

        if self._pending_long and m1_bar.close > self._pending_long.level:
            stop = self._pending_long.wick_extreme
            risk = m1_bar.close - stop
            if risk > 0 and vp.vwap > m1_bar.close:
                take_profit = vp.vwap
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=m1_bar.close,
                        stop_loss=stop,
                        take_profit=take_profit,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vp_absorption_long", "target": "vwap"},
                    )
                )
            self._pending_long = None

        return signals
