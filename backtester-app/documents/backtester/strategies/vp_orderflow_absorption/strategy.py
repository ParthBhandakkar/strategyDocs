"""
Video #1 — Orderflow and Volume Profile Day Trading Strategy.
Fade absorption at developing VP extremes with order-cluster inversion.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import is_after_ny_open, get_session_bars_since_ny_open
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy
from .helpers import (
    detect_buyer_absorption_at_high,
    detect_seller_absorption_at_low,
    find_local_support_cluster,
    find_local_resistance_cluster,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade failed absorption at developing session VP extremes. "
        "Short above VAH/POC after buyer absorption + cluster inversion; "
        "long below VAL after seller absorption + reclaim."
    )
    timeframes = [TF.M1, TF.D1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1, "Session VP", "Build developing VP from 9:30 NY open on M1 bars.", "M1",
            conditions=["Post 9:30 NY", "Use tick_volume FRVP proxy"],
            key_levels=["POC", "VAH", "VAL", "VWAP midpoint"],
        ),
        PlaybookStep(
            2, "Absorption", "Identify wick-heavy volume without follow-through.", "M1",
            conditions=["Upper wick buyer absorption at VAH/POC", "Lower wick seller absorption at VAL"],
        ),
        PlaybookStep(
            3, "Inversion Entry", "Enter on close through local order cluster.", "M1",
            conditions=["Short: close below support cluster", "Long: close above resistance cluster"],
        ),
        PlaybookStep(
            4, "Risk", "SL beyond absorption wick; TP at VAL (short) or POC/VWAP (long).", "M1",
        ),
    ]

    def on_start(self):
        self._last_absorption: str | None = None
        self._absorption_high: float = 0.0
        self._absorption_low: float = 0.0

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if not m1 or not is_after_ny_open(current_time):
            return []

        m1_hist = history(self.symbol, TF.M1, 500)
        if len(m1_hist) < 30:
            return []

        session_bars = get_session_bars_since_ny_open(m1_hist, current_time)
        if len(session_bars) < 15:
            return []

        vp = compute_frvp(session_bars, row_size=50, va_pct=70.0)
        if vp is None:
            return []

        vwap = sum(b.close * max(b.tick_volume, 1) for b in session_bars) / sum(
            max(b.tick_volume, 1) for b in session_bars
        )
        price = m1.close
        signals: list[Signal] = []

        near_vah = price >= vp.vah * 0.9995
        near_val = price <= vp.val * 1.0005
        near_poc = abs(price - vp.poc) <= (vp.vah - vp.val) * 0.05

        # Track absorption events (no future data — current bar only)
        if (near_vah or near_poc) and detect_buyer_absorption_at_high(m1):
            self._last_absorption = "short_setup"
            self._absorption_high = m1.high

        if near_val and detect_seller_absorption_at_low(m1):
            self._last_absorption = "long_setup"
            self._absorption_low = m1.low

        if self._last_absorption == "short_setup":
            cluster = find_local_support_cluster(m1_hist[:-1], lookback=10)
            if cluster and m1.close < cluster and m1.is_bearish:
                sl = max(self._absorption_high, m1.high) + (vp.vah - vp.val) * 0.02
                risk = sl - m1.close
                if risk > 0:
                    tp = max(vp.val, m1.close - risk)
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=m1.close,
                            stop_loss=sl,
                            take_profit=tp,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "vah_absorption_inversion", "cluster": cluster},
                        )
                    )
                    self._last_absorption = None

        elif self._last_absorption == "long_setup":
            cluster = find_local_resistance_cluster(m1_hist[:-1], lookback=10)
            if cluster and m1.close > cluster and m1.is_bullish:
                sl = min(self._absorption_low, m1.low) - (vp.vah - vp.val) * 0.02
                risk = m1.close - sl
                if risk > 0:
                    tp = min(vwap, m1.close + risk * 2)
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=m1.close,
                            stop_loss=sl,
                            take_profit=tp,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "val_absorption_reclaim", "cluster": cluster},
                        )
                    )
                    self._last_absorption = None

        return signals
