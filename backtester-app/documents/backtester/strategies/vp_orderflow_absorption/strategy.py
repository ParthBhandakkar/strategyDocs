"""
VP + Orderflow Absorption — Video #1 (Cluster A).

Fade failed aggressive orderflow at developing daily VP extremes after NY open.
Uses tick_volume wick ratios as L2 absorption proxy on Exness CSV data.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.strategies.base import BaseStrategy
from backtester.indicators.sessions import is_post_ny_open, get_ny_time
from backtester.indicators.volume_profile import (
    compute_frvp,
    get_session_bars_since_ny_open,
)
from backtester.indicators.orderflow import (
    detect_buyer_absorption,
    detect_seller_absorption,
    find_support_cluster,
    find_resistance_cluster,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at wicks "
        "and price inverts order clusters. Post 9:30 NY session."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    # Fixed params from video spec — not tuned on backtest data
    MIN_WICK_RATIO = 0.35
    MIN_VOLUME = 30
    VP_PROXIMITY_PCT = 0.0015  # price within 0.15% of VP level
    CLUSTER_LOOKBACK = 12

    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing Daily VP",
            description="Build session VP (VWAP/POC/VAH/VAL) from NY 9:30 open bars.",
            timeframe="M1",
            conditions=["Post 9:30 NY", "Minimum session bars for VP"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption at Extremes",
            description="Identify buyer absorption at upper wicks near VAH/POC/VWAP or seller absorption below VAL.",
            timeframe="M1",
            conditions=["Heavy wick volume without follow-through"],
            key_levels=["VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Order Cluster Inversion",
            description="Enter on close through nearby support/resistance cluster after absorption.",
            timeframe="M1",
            conditions=["Bearish close below support after buyer absorption", "Bullish close above resistance after seller absorption"],
            key_levels=["Local order cluster"],
        ),
    ]

    def on_start(self):
        self._last_trade_date = None

    def on_bar(self, bars, history, multi_symbol_bars, current_time: datetime) -> list[Signal]:
        if TF.M1 not in bars:
            return []

        if not is_post_ny_open(current_time):
            return []

        m1_hist = history(None, TF.M1, 500)
        if len(m1_hist) < 30:
            return []

        bar = bars[TF.M1]
        session_bars = get_session_bars_since_ny_open(m1_hist, current_time)
        if len(session_bars) < 20:
            return []

        vp = compute_frvp(session_bars, row_size=80, va_pct=70.0)
        if vp is None:
            return []

        # One trade per NY session day max (avoid overtrading same setup)
        ny_date = get_ny_time(current_time).date()
        if self._last_trade_date == ny_date:
            return []

        signals: list[Signal] = []

        short_signal = self._check_short_setup(bar, m1_hist, vp, current_time)
        if short_signal:
            self._last_trade_date = ny_date
            return [short_signal]

        long_signal = self._check_long_setup(bar, m1_hist, vp, current_time)
        if long_signal:
            self._last_trade_date = ny_date
            return [long_signal]

        return signals

    def _near_level(self, price: float, level: float) -> bool:
        if level <= 0:
            return False
        return abs(price - level) / level <= self.VP_PROXIMITY_PCT

    def _check_short_setup(
        self, bar: Bar, hist: list[Bar], vp, current_time: datetime
    ) -> Signal | None:
        """Short after buyer absorption at upper VP extremes + cluster inversion."""
        at_upper_extreme = (
            self._near_level(bar.high, vp.vah)
            or self._near_level(bar.high, vp.poc)
            or self._near_level(bar.high, vp.vwap)
        )
        if not at_upper_extreme:
            return None

        if not detect_buyer_absorption(bar, self.MIN_WICK_RATIO, self.MIN_VOLUME):
            return None

        support = find_support_cluster(hist, self.CLUSTER_LOOKBACK)
        if support is None:
            return None

        # Inversion: close below support cluster (prior aggressive buy zone fails)
        if bar.close >= support:
            return None

        stop_loss = bar.high + bar.total_range * 0.1
        take_profit = vp.val
        if take_profit >= bar.close:
            take_profit = bar.close - abs(stop_loss - bar.close)

        return Signal(
            strategy_id=self.id,
            direction=Direction.SHORT,
            entry_price=bar.close,
            stop_loss=stop_loss,
            take_profit=take_profit,
            timestamp=current_time,
            symbol=self.symbol,
            metadata={"setup": "buyer_absorption_vah", "cluster": support},
        )

    def _check_long_setup(
        self, bar: Bar, hist: list[Bar], vp, current_time: datetime
    ) -> Signal | None:
        """Long after seller absorption below VAL + cluster inversion."""
        below_val = bar.low < vp.val or self._near_level(bar.low, vp.val)
        if not below_val:
            return None

        if not detect_seller_absorption(bar, self.MIN_WICK_RATIO, self.MIN_VOLUME):
            return None

        resistance = find_resistance_cluster(hist, self.CLUSTER_LOOKBACK)
        if resistance is None:
            return None

        if bar.close <= resistance:
            return None

        stop_loss = bar.low - bar.total_range * 0.1
        take_profit = vp.vwap
        if take_profit <= bar.close:
            take_profit = bar.close + abs(bar.close - stop_loss) * 2

        return Signal(
            strategy_id=self.id,
            direction=Direction.LONG,
            entry_price=bar.close,
            stop_loss=stop_loss,
            take_profit=take_profit,
            timestamp=current_time,
            symbol=self.symbol,
            metadata={"setup": "seller_absorption_val", "cluster": resistance},
        )
