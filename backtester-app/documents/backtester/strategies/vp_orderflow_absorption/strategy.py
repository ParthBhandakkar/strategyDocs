"""
Video #1 — Orderflow and Volume Profile absorption at developing VP extremes.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import is_post_ny_open, session_bars_since_ny_open
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy
from .helpers import (
    is_buyer_absorption,
    is_seller_absorption,
    recent_swing_low,
    recent_swing_high,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail "
        "at wicks and price inverts order clusters after NY open."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session VP (VWAP/POC/VAH/VAL) from M1 bars after 09:30 NY.",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Detect buyer/seller absorption via high tick_volume trapped in wicks.",
            "M1",
        ),
        PlaybookStep(
            3,
            "Inversion Entry",
            "Enter on close through nearby order cluster after absorption at VA extremes.",
            "M1",
        ),
    ]

    def on_start(self):
        self._last_session_day = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        if not is_post_ny_open(current_time):
            return []

        m1_bar = bars.get(TF.M1)
        if not m1_bar:
            return []

        m1_hist = history(self.symbol, TF.M1, 500)
        if len(m1_hist) < 30:
            return []

        session_bars = session_bars_since_ny_open(m1_hist, current_time)
        if len(session_bars) < 20:
            return []

        vp = compute_frvp(session_bars)
        if vp is None:
            return []

        signals: list[Signal] = []

        near_vah = m1_bar.high >= vp.vah * 0.9995
        below_val = m1_bar.close <= vp.val * 1.0005

        prev = m1_hist[-2] if len(m1_hist) >= 2 else None

        if near_vah and prev and is_buyer_absorption(prev):
            support = recent_swing_low(m1_hist, lookback=10)
            if support and m1_bar.close < support:
                stop = max(prev.high, m1_bar.high)
                risk = stop - m1_bar.close
                if risk > 0:
                    target = vp.val
                    if target < m1_bar.close:
                        target = m1_bar.close - risk
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=m1_bar.close,
                            stop_loss=stop,
                            take_profit=target,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "vah_buyer_absorption_inversion"},
                        )
                    )

        if below_val and prev and is_seller_absorption(prev):
            resistance = recent_swing_high(m1_hist, lookback=10)
            if resistance and m1_bar.close > resistance and m1_bar.is_bullish:
                stop = min(prev.low, m1_bar.low)
                risk = m1_bar.close - stop
                if risk > 0:
                    target = vp.vwap
                    if target <= m1_bar.close:
                        target = m1_bar.close + risk * 2
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=m1_bar.close,
                            stop_loss=stop,
                            take_profit=target,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "val_seller_absorption_inversion"},
                        )
                    )

        return signals
