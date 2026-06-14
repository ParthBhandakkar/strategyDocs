"""
Strategy 41: ICT Daily Bias Simplified
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from .base import BaseStrategy


class ICTDailyBiasSimplified(BaseStrategy):
    id = "s041_ict_daily_bias_simplified"
    name = "ICT Daily Bias Simplified"
    source_video = ""
    description = "Simplified daily bias approach for clear directional trading."
    timeframes = [TF.D1, TF.H4, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Previous Day", "Analyze previous D1 candle.", "D1"),
        PlaybookStep(2, "Bias", "Set bullish/bearish bias.", "D1"),
        PlaybookStep(3, "H4 Entry", "Wait for H4 setup.", "H4"),
        PlaybookStep(4, "Execute", "M1 entry with D1 bias.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_BIAS"

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []