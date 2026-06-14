"""
Strategy 33: Stupid Simple Gold Trading Strategy
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from .base import BaseStrategy


class StupidSimpleGold(BaseStrategy):
    id = "s033_stupid_simple_gold"
    name = "Stupid Simple Gold"
    source_video = ""
    description = "Simple Gold strategy using London session range breakouts."
    timeframes = [TF.M5, TF.M1]
    
    playbook = [
        PlaybookStep(1, "London Range", "Map London session (3AM-7AM) range.", "M5"),
        PlaybookStep(2, "NY Breakout", "Wait for M5 close outside London range.", "M5"),
        PlaybookStep(3, "Execute", "Enter on retest. Target 1:2.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_LONDON"
        self.london_high = 0.0
        self.london_low = 0.0

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []