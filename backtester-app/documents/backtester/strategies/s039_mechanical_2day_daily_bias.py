"""
Strategy 39: Mechanical 2-Day Daily Bias Strategy
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from .base import BaseStrategy


class MechanicalTwoDayBias(BaseStrategy):
    id = "s039_mechanical_2day_daily_bias"
    name = "2-Day Daily Bias"
    source_video = ""
    description = "Uses previous 2 days to establish daily bias and key levels."
    timeframes = [TF.D1, TF.H4, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "2-Day Analysis", "Analyze previous 2 D1 candles.", "D1"),
        PlaybookStep(2, "Daily Bias", "Determine bullish/bearish bias.", "D1"),
        PlaybookStep(3, "Key Levels", "Map H4 support/resistance.", "H4"),
        PlaybookStep(4, "Execute", "M15/M1 entry with bias.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_ANALYSIS"

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []