"""Video #1 — VP + Orderflow Absorption (Cluster A canonical)."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.strategies.base import BaseStrategy
from backtester.indicators.sessions import get_ny_time
from backtester.strategies.vp_orderflow_absorption.helpers import evaluate_absorption_setup


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    module_id = "vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at "
        "wicks and price inverts local order clusters after NY open."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP",
            description="Build session VP from M1 bars after 9:30 NY open.",
            timeframe="M1",
            conditions=["Post 9:30 NY", "Minimum session bars accumulated"],
            key_levels=["POC", "VAH", "VAL", "VWAP"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption at extremes",
            description="Identify wick absorption at VAH/POC (short) or below VAL (long).",
            timeframe="M1",
            conditions=["High tick_volume in wick vs body", "No follow-through"],
            key_levels=["VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Order cluster inversion",
            description="Enter on close through nearby swing cluster after absorption.",
            timeframe="M1",
            conditions=["Bearish close below cluster (short)", "Bullish close above cluster (long)"],
            key_levels=["Local swing cluster"],
        ),
    ]

    def on_start(self):
        self._last_signal_day = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        bar = bars.get(TF.M1)
        if bar is None:
            return []

        m1_history = history(None, TF.M1, 500)
        if len(m1_history) < 40:
            return []

        setup = evaluate_absorption_setup(m1_history, bar)
        if setup is None:
            return []

        ny_date = get_ny_time(bar.time).date()
        if self._last_signal_day == ny_date:
            return []

        if setup.direction == "SHORT":
            entry = bar.close
            stop = setup.absorption_high
            target = setup.vp.val
            direction = Direction.SHORT
        else:
            entry = bar.close
            stop = setup.absorption_low
            target = setup.vwap
            direction = Direction.LONG

        if direction == Direction.SHORT and not (target < entry < stop):
            return []
        if direction == Direction.LONG and not (stop < entry < target):
            return []

        self._last_signal_day = ny_date
        return [
            Signal(
                strategy_id=self.id,
                direction=direction,
                entry_price=entry,
                stop_loss=stop,
                take_profit=target,
                timestamp=current_time,
                symbol=self.symbol,
                metadata={
                    "cluster_level": setup.cluster_level,
                    "poc": setup.vp.poc,
                    "vah": setup.vp.vah,
                    "val": setup.vp.val,
                    "vwap": setup.vwap,
                },
            )
        ]
