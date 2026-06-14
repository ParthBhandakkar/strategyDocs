"""
Strategy 37: The 1-Candle Hourly Range Strategy
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from .base import BaseStrategy


class OneCandleHourlyRange(BaseStrategy):
    id = "s037_one_candle_hourly_range"
    name = "1-Candle Hourly Range"
    source_video = ""
    description = "Uses single hourly candle range for intraday range trading."
    timeframes = [TF.H1, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Hourly Range", "Map current H1 candle range.", "H1"),
        PlaybookStep(2, "Wait Break", "Price must break range.", "H1"),
        PlaybookStep(3, "Retest", "Wait for retest.", "M15"),
        PlaybookStep(4, "Execute", "M1 entry on retest.", "M1")
    ]

    def on_start(self):
        self.state = "MONITOR"

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []