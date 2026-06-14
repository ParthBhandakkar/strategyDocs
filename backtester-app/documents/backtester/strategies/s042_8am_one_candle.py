"""
Strategy 42: The 8 AM One-Candle Trading Strategy
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from .base import BaseStrategy


class EightAMOneCandle(BaseStrategy):
    id = "s042_8am_one_candle"
    name = "8AM One-Candle Strategy"
    source_video = ""
    description = "Uses 8:00 AM hourly candle for single-candle trade setups."
    timeframes = [TF.H1, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "8AM Candle", "Mark 8AM H1 candle.", "H1"),
        PlaybookStep(2, "Breakout", "Wait for close outside 8AM range.", "M15"),
        PlaybookStep(3, "Retest", "Retest entry on M1.", "M1"),
        PlaybookStep(4, "Target", "1:2 RR target.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_8AM"

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []