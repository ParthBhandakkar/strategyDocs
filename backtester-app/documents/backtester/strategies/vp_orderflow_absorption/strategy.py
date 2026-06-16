"""
Video #1: Orderflow and Volume Profile Day Trading Strategy.
Fade absorption at developing VP extremes with order-cluster inversion.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.orderflow import (
    detect_buyer_absorption,
    detect_seller_absorption,
    nearest_support_cluster,
)
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import build_session_profile


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at wicks "
        "and price inverts local order clusters after 9:30 NY."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(1, "Developing VP", "Build session VP (VWAP/POC/VAH/VAL) from 9:30 NY.", "M1"),
        PlaybookStep(2, "Absorption", "Identify buyer/seller absorption at VP extremes via wick volume.", "M1"),
        PlaybookStep(3, "Inversion", "Enter on close through nearby order cluster (support/resistance flip).", "M1"),
        PlaybookStep(4, "Targets", "Target VAL for shorts above VAH; VWAP for longs below VAL.", "M1"),
    ]

    def on_start(self):
        self._last_trade_day = None
        self._absorption_high = None
        self._absorption_low = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if m1 is None:
            return []

        if not is_in_session(current_time, "new_york"):
            return []

        ny_time = get_ny_time(current_time)
        if ny_time.hour < 9 or (ny_time.hour == 9 and ny_time.minute < 30):
            return []

        m1_hist = history(self.symbol, TF.M1, 400)
        if len(m1_hist) < 30:
            return []

        profile, vwap = build_session_profile(m1_hist, current_time)
        if profile is None:
            return []

        signals: list[Signal] = []
        day_key = ny_time.date()
        if self._last_trade_day == day_key and self.broker and self.broker.has_open_position(self.id):
            return []

        support_cluster = nearest_support_cluster(m1_hist[:-1], lookback=8)
        min_wick = max(m1.close * 0.00005, 0.0001)

        near_vah = m1.high >= profile.vah * 0.9995 or abs(m1.high - profile.poc) / profile.poc < 0.001
        near_vwap_poc = vwap is not None and abs(m1.high - vwap) / vwap < 0.0015
        if (near_vah or near_vwap_poc) and detect_buyer_absorption(m1, min_wick_ratio=1.2):
            self._absorption_high = m1.high
            if support_cluster and m1.close < support_cluster and m1.is_bearish:
                stop = (self._absorption_high or m1.high) + min_wick
                target = profile.val
                risk = stop - m1.close
                if risk > 0:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=m1.close,
                            stop_loss=stop,
                            take_profit=max(target, m1.close - risk),
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "buyer_absorption_vah", "cluster": support_cluster},
                        )
                    )
                    self._last_trade_day = day_key

        below_val = m1.close < profile.val
        if below_val and detect_seller_absorption(m1, min_wick_ratio=1.2):
            self._absorption_low = m1.low
            resistance_cluster = max(bar.high for bar in m1_hist[-8:])
            if m1.is_bullish and m1.close > resistance_cluster:
                stop = (self._absorption_low or m1.low) - min_wick
                target = vwap if vwap is not None else profile.poc
                risk = m1.close - stop
                if risk > 0:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=m1.close,
                            stop_loss=stop,
                            take_profit=max(target, m1.close + risk * 2),
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "seller_absorption_val", "cluster": resistance_cluster},
                        )
                    )
                    self._last_trade_day = day_key

        return signals
