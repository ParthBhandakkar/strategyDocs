"""
Strategy 21: Trading Strategy That Will Change Your Life
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from .base import BaseStrategy


class ChangeLifeStrategy(BaseStrategy):
    id = "s021_trading_strategy_change_life"
    name = "Strategy That Changes Life"
    source_video = ""
    description = "High-probability setup combining killzone timing with liquidity sweep entries."
    timeframes = [TF.H1, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Killzone Filter", "Only trade during NY killzone.", "H1"),
        PlaybookStep(2, "Liquidity Sweep", "Wait for H1 liquidity sweep.", "H1"),
        PlaybookStep(3, "M15 Entry", "Confirm on M15 FVG.", "M15"),
        PlaybookStep(4, "Execute", "Enter on M1 MSS.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_KILLZONE"

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []