"""
VP + Orderflow Absorption — Video #1 canonical strategy.
Fade failed aggression at developing VP extremes after NY open.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.strategies.base import BaseStrategy
from backtester.indicators.sessions import is_after_ny_open, get_ny_time
from backtester.indicators.volume_profile import compute_frvp

from .helpers import (
    session_bars_for_day,
    detect_wick_absorption,
    is_near_vah_zone,
    is_below_val,
    find_support_cluster,
    find_resistance_cluster,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail "
        "at wicks and price inverts order clusters post 9:30 NY."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP Setup",
            description="Build session VP from M1 bars after 9:30 NY open.",
            timeframe="M1",
            conditions=["Post 9:30 NY", "Developing daily VP active"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption Detection",
            description="Identify wick absorption via tick_volume proxy at VAH/VAL extremes.",
            timeframe="M1",
            conditions=["Heavy volume in wick", "No follow-through in body"],
        ),
        PlaybookStep(
            step_number=3,
            title="Order Inversion Entry",
            description="Enter on close through local order cluster after absorption.",
            timeframe="M1",
            conditions=["Bearish close below support cluster at VAH", "Bullish close above cluster at VAL"],
        ),
    ]

    def on_start(self) -> None:
        self._last_trade_day = None
        self._trades_today = 0
        self._max_trades_per_day = 3

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        if TF.M1 not in bars:
            return []

        if not is_after_ny_open(current_time):
            return []

        bar = bars[TF.M1]
        m1_history = history(None, TF.M1, 500)
        if len(m1_history) < 30:
            return []

        ny_date = get_ny_time(current_time).date()
        if self._last_trade_day != ny_date:
            self._last_trade_day = ny_date
            self._trades_today = 0

        if self._trades_today >= self._max_trades_per_day:
            return []

        session_bars = session_bars_for_day(m1_history, current_time)
        if len(session_bars) < 15:
            return []

        vp = compute_frvp(session_bars)
        if vp is None:
            return []

        absorption = detect_wick_absorption(bar)
        if not absorption:
            return []

        signals: list[Signal] = []

        if absorption == "buyer" and is_near_vah_zone(bar.high, vp):
            _, cluster_high = find_support_cluster(m1_history[:-1])
            if cluster_high > 0 and bar.close < cluster_high and bar.is_bearish:
                sl = bar.high
                entry = bar.close
                risk = sl - entry
                if risk > 0:
                    tp = max(vp.val, entry - risk)
                    signals.append(Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "vah_buyer_absorption", "vah": vp.vah},
                    ))
                    self._trades_today += 1

        elif absorption == "seller" and is_below_val(bar.low, vp):
            cluster_low, _ = find_resistance_cluster(m1_history[:-1])
            if cluster_low > 0 and bar.close > cluster_low and bar.is_bullish:
                sl = bar.low
                entry = bar.close
                risk = entry - sl
                if risk > 0:
                    tp = min(vp.vwap, entry + risk * 2)
                    signals.append(Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "val_seller_absorption", "val": vp.val},
                    ))
                    self._trades_today += 1

        return signals
