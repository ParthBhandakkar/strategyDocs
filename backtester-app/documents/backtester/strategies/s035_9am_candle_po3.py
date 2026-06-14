"""
Strategy 35: Easy 9AM Candle PO3 Strategy
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from .base import BaseStrategy


class NineAMCandlePO3(BaseStrategy):
    id = "s035_9am_candle_po3"
    name = "9AM Candle PO3"
    source_video = ""
    description = "Uses 9:00 AM candle for PO3 entry during NY session."
    timeframes = [TF.H1, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "9AM Anchor", "Mark 9:00 AM H1 open.", "H1"),
        PlaybookStep(2, "Manipulation", "Wait for price to cross open.", "M15"),
        PlaybookStep(3, "MSS", "Enter on M15 MSS.", "M15"),
        PlaybookStep(4, "Target", "Target -2.0 SD.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_9AM"
        self.open_9am = 0.0

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []