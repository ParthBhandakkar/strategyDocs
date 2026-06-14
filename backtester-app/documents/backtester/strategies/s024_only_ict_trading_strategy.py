"""
Strategy 24: The Only ICT Trading Strategy I'll Be Using
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from .base import BaseStrategy


class OnlyICTStrategy(BaseStrategy):
    id = "s024_only_ict_trading_strategy"
    name = "Only ICT Strategy"
    source_video = ""
    description = "Consolidated ICT approach using multiple concepts: FVG, Order Blocks, Liquidity."
    timeframes = [TF.H1, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "H1 Trend", "Determine H1 orderflow.", "H1"),
        PlaybookStep(2, "Key Level", "Map H1 swing points.", "H1"),
        PlaybookStep(3, "M15 FVG/OB", "Wait for M15 FVG or Order Block near H1 level.", "M15"),
        PlaybookStep(4, "M1 Entry", "Enter on M1 MSS.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_BIAS"
        self.bias = None

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []