from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session, session_bars_for_day
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    average_volume,
    buyer_absorption_at_wick,
    nearest_resistance_cluster,
    nearest_support_cluster,
    near_level,
    seller_absorption_at_wick,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at wicks "
        "and price inverts local order clusters after the NY open."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP",
            description="Build session volume profile after 9:30 NY.",
            timeframe="M1",
            conditions=["Post 9:30 NY session"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption",
            description="Detect wick absorption using tick-volume proxy.",
            timeframe="M1",
            conditions=["Heavy volume in wick without follow-through"],
            key_levels=["VAH for shorts", "VAL for longs"],
        ),
        PlaybookStep(
            step_number=3,
            title="Cluster inversion",
            description="Enter on close through nearby support/resistance cluster.",
            timeframe="M1",
            conditions=["Close below support cluster for shorts", "Close above resistance cluster for longs"],
            key_levels=["Local order cluster"],
        ),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None
        self._last_trade_day: datetime | None = None
        self._trades_today = 0
        self._max_trades_per_day = 2

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        if not is_in_session(current_time, "post_open"):
            return []

        m1_bar = bars.get(TF.M1)
        if m1_bar is None:
            return []

        m1_history = history(timeframe=TF.M1, lookback=500)
        if len(m1_history) < 30:
            return []

        ny_day = get_ny_time(current_time).date()
        if self._last_trade_day != ny_day:
            self._last_trade_day = ny_day
            self._trades_today = 0
            self._pending_short = None
            self._pending_long = None

        if self._trades_today >= self._max_trades_per_day:
            return []

        session_bars = session_bars_for_day(m1_history, current_time, "post_open")
        if len(session_bars) < 20:
            return []

        profile = compute_frvp(session_bars)
        if profile is None:
            return []

        avg_vol = average_volume(m1_history)
        signals: list[Signal] = []

        if (
            near_level(m1_bar.high, profile.vah)
            or near_level(m1_bar.high, profile.vwap)
            or near_level(m1_bar.high, profile.poc)
        ):
            if buyer_absorption_at_wick(m1_bar, avg_vol):
                cluster = nearest_support_cluster(m1_history[:-1])
                self._pending_short = {
                    "cluster": cluster,
                    "absorption_high": m1_bar.high,
                    "target": profile.val,
                }

        if m1_bar.close < profile.val or near_level(m1_bar.low, profile.val):
            if seller_absorption_at_wick(m1_bar, avg_vol):
                cluster = nearest_resistance_cluster(m1_history[:-1])
                self._pending_long = {
                    "cluster": cluster,
                    "absorption_low": m1_bar.low,
                    "target": profile.vwap,
                }

        if self._pending_short and m1_bar.close < self._pending_short["cluster"]:
            entry = m1_bar.close
            stop = self._pending_short["absorption_high"]
            risk = stop - entry
            if risk > 0:
                target = self._pending_short["target"]
                if target >= entry:
                    target = entry - risk
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=target,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "short_absorption_inversion"},
                    )
                )
                self._pending_short = None
                self._trades_today += 1

        if self._pending_long and m1_bar.close > self._pending_long["cluster"]:
            entry = m1_bar.close
            stop = self._pending_long["absorption_low"]
            risk = entry - stop
            if risk > 0:
                target = self._pending_long["target"]
                if target <= entry:
                    target = entry + (risk * 2)
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=target,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "long_absorption_inversion"},
                    )
                )
                self._pending_long = None
                self._trades_today += 1

        return signals
