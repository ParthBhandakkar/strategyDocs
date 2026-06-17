"""
Video #1 — VP + Orderflow Absorption (Cluster A canonical).
Fade absorption at developing VP extremes; order-cluster inversion on M1.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Direction, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.orderflow import (
    detect_buyer_absorption_at_high,
    detect_seller_absorption_at_low,
    find_recent_resistance_cluster,
    find_recent_support_cluster,
)
from backtester.indicators.sessions import get_ny_time, get_session_bars_since_open, is_in_session
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade buyer/seller absorption at developing daily VP extremes after NY open; "
        "enter on order-cluster inversion confirmed by M1 close."
    )
    timeframes = [TF.M1]
    extra_symbols: list[str] = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session VP from 9:30 NY open; track POC, VAH, VAL, VWAP proxy.",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption at Extremes",
            "Detect wick absorption at VAH/POC (short) or VAL (long).",
            "M1",
        ),
        PlaybookStep(
            3,
            "Order Inversion",
            "Enter when M1 closes through nearby support/resistance cluster.",
            "M1",
        ),
        PlaybookStep(
            4,
            "Risk Management",
            "SL beyond absorption wick; TP at VAL (short) or VWAP (long).",
            "M1",
        ),
    ]

    def on_start(self):
        self._absorption_high: float | None = None
        self._absorption_low: float | None = None
        self._pending_short = False
        self._pending_long = False

    def _session_vwap(self, bars: list[Bar]) -> float:
        if not bars:
            return 0.0
        total_vol = sum(max(b.tick_volume, 1) for b in bars)
        if total_vol <= 0:
            return bars[-1].close
        weighted = sum(
            ((b.high + b.low + b.close) / 3.0) * max(b.tick_volume, 1) for b in bars
        )
        return weighted / total_vol

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

        if not is_in_session(current_time, "new_york"):
            return []

        ny_time = get_ny_time(current_time)
        if ny_time.hour < 9 or (ny_time.hour == 9 and ny_time.minute < 30):
            return []

        m1_hist = history(self.symbol, TF.M1, 500)
        session_bars = get_session_bars_since_open(m1_hist, current_time, "new_york")
        if len(session_bars) < 20:
            return []

        vp = compute_frvp(session_bars, row_size=50)
        if vp is None:
            return []

        vwap = self._session_vwap(session_bars)
        recent = m1_hist[-12:]

        signals: list[Signal] = []

        near_vah = m1_bar.high >= vp.vah * 0.9995
        near_val = m1_bar.low <= vp.val * 1.0005
        near_poc = abs(m1_bar.close - vp.poc) <= (vp.vah - vp.val) * 0.05

        if near_vah or (near_poc and m1_bar.close > vp.poc):
            if detect_buyer_absorption_at_high(m1_bar):
                self._absorption_high = m1_bar.high
                self._pending_short = True
                self._pending_long = False

        if near_val:
            if detect_seller_absorption_at_low(m1_bar):
                self._absorption_low = m1_bar.low
                self._pending_long = True
                self._pending_short = False

        if self._pending_short and self._absorption_high is not None:
            cluster = find_recent_support_cluster(recent)
            if cluster and m1_bar.close < cluster:
                stop = self._absorption_high + m1_bar.total_range * 0.1
                risk = stop - m1_bar.close
                take_profit = vp.val if vp.val < m1_bar.close else m1_bar.close - risk
                if risk > 0 and take_profit < m1_bar.close:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=m1_bar.close,
                            stop_loss=stop,
                            take_profit=take_profit,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "vah_absorption_inversion"},
                        )
                    )
                self._pending_short = False
                self._absorption_high = None

        if self._pending_long and self._absorption_low is not None:
            cluster = find_recent_resistance_cluster(recent)
            if cluster and m1_bar.close > cluster:
                stop = self._absorption_low - m1_bar.total_range * 0.1
                risk = m1_bar.close - stop
                take_profit = vwap if vwap > m1_bar.close else m1_bar.close + risk
                if risk > 0 and take_profit > m1_bar.close:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=m1_bar.close,
                            stop_loss=stop,
                            take_profit=take_profit,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "val_absorption_inversion"},
                        )
                    )
                self._pending_long = False
                self._absorption_low = None

        return signals
