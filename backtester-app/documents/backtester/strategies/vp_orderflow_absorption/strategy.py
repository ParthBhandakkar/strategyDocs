"""
VP + Orderflow Absorption — Video #1 canonical strategy.

Fade absorption at developing VP extremes when aggressive orders fail at wicks
and price inverts local order clusters. Uses tick_volume wick proxy for L2
orderflow (no footprint data in CSV backtests).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.volume_profile import compute_frvp, wick_volume_ratio
from backtester.strategies.base import BaseStrategy


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade failed absorption at developing daily VP extremes after NY open. "
        "Short when buyer absorption at VAH/POC/VWAP fails and price inverts "
        "below local support; long when seller absorption below VAL fails upward."
    )
    timeframes = [TF.M1, TF.D1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP Setup",
            description="After 9:30 NY, compute developing session VP (POC/VAH/VAL/VWAP).",
            timeframe="M1",
            conditions=["Post 9:30 NY session", "Minimum session bars accumulated"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption Detection",
            description="Identify wick-heavy volume at VP extremes without follow-through.",
            timeframe="M1",
            conditions=["Upper wick volume > body volume at VAH/POC", "Lower wick volume at VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Order Inversion Entry",
            description="Enter on close through local swing cluster after absorption.",
            timeframe="M1",
            conditions=["Close below support cluster (short)", "Close above sell cluster (long)"],
        ),
    ]

    def on_start(self):
        self._absorption_wick_ratio = 1.5
        self._vp_proximity_pct = 0.0015
        self._swing_lookback = 5
        self._min_session_bars = 30
        self._last_signal_day: datetime | None = None
        self._trades_today = 0
        self._max_trades_per_day = 3

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if m1 is None:
            return []

        if not is_in_session(current_time, "ny_am") and not is_in_session(current_time, "ny_pm"):
            return []

        ny_now = get_ny_time(current_time)
        if ny_now.hour == 9 and ny_now.minute < 30:
            return []

        ny_date = ny_now.date()
        if self._last_signal_day != ny_date:
            self._last_signal_day = ny_date
            self._trades_today = 0

        if self._trades_today >= self._max_trades_per_day:
            return []

        m1_hist = history(None, TF.M1, 500)
        if len(m1_hist) < self._min_session_bars:
            return []

        session_bars = [
            b for b in m1_hist
            if get_ny_time(b.time).date() == ny_date and (
                (get_ny_time(b.time).hour > 9)
                or (get_ny_time(b.time).hour == 9 and get_ny_time(b.time).minute >= 30)
            )
        ]
        if len(session_bars) < self._min_session_bars:
            return []

        vp = compute_frvp(session_bars[-120:], row_size=50)
        if vp is None:
            return []

        upper_wick_vol, lower_wick_vol = wick_volume_ratio(m1)
        body_vol = max((m1.tick_volume or 1) - upper_wick_vol - lower_wick_vol, 1)

        swing_low = min(b.low for b in m1_hist[-self._swing_lookback :])
        swing_high = max(b.high for b in m1_hist[-self._swing_lookback :])
        proximity = m1.close * self._vp_proximity_pct

        signals: list[Signal] = []

        near_vah = abs(m1.high - vp.vah) <= proximity or abs(m1.high - vp.poc) <= proximity
        near_vwap_upper = abs(m1.high - vp.vwap) <= proximity and m1.high >= vp.vwap

        buyer_absorption = (
            (near_vah or near_vwap_upper)
            and upper_wick_vol >= body_vol * self._absorption_wick_ratio
            and m1.upper_wick > m1.body_size
        )

        if buyer_absorption and m1.close < swing_low and m1.is_bearish:
            sl = max(m1.high, swing_high) + proximity
            risk = sl - m1.close
            if risk > 0:
                tp = m1.close - risk
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=m1.close,
                        stop_loss=sl,
                        take_profit=max(tp, vp.val),
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "buyer_absorption_vah", "vp_poc": vp.poc},
                    )
                )

        near_val = abs(m1.low - vp.val) <= proximity
        seller_absorption = (
            near_val
            and lower_wick_vol >= body_vol * self._absorption_wick_ratio
            and m1.lower_wick > m1.body_size
        )

        if seller_absorption and m1.close > swing_high and m1.is_bullish:
            sl = min(m1.low, swing_low) - proximity
            risk = m1.close - sl
            if risk > 0:
                tp = m1.close + risk * 2
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=m1.close,
                        stop_loss=sl,
                        take_profit=min(tp, vp.vwap),
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "seller_absorption_val", "vp_poc": vp.poc},
                    )
                )

        if signals:
            self._trades_today += 1
        return signals
