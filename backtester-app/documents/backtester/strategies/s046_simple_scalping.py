"""
Strategy 46: Simple Scalping Trading Strategy
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from .base import BaseStrategy


class SimpleScalping(BaseStrategy):
    id = "s046_simple_scalping"
    name = "Simple Scalping Strategy"
    source_video = ""
    description = "Simple scalping approach for quick trades during volatile periods."
    timeframes = [TF.M15, TF.M5, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Trend", "M15 clear trend.", "M15"),
        PlaybookStep(2, "Pullback", "Wait for pullback.", "M15"),
        PlaybookStep(3, "Entry", "M1 entry on trend resumption.", "M1"),
        PlaybookStep(4, "Quick Exit", "1:1 or quick flip.", "M1")
    ]

    def on_start(self):
        self.state = "MONITOR"

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []