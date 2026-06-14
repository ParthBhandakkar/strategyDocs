"""
Strategy 25: The 3-Step A ICT Strategy That Works Every Time
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from .base import BaseStrategy


class ThreeStepAICTStrategyV2(BaseStrategy):
    id = "s025_3step_a_ict_strategy"
    name = "3-Step A ICT Strategy"
    source_video = ""
    description = "Three-step ICT approach: Structure -> Liquidity -> Entry."
    timeframes = [TF.H1, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Market Structure", "Identify H1 trend and MSS.", "H1"),
        PlaybookStep(2, "Liquidity Pools", "Map H1 swing highs/lows.", "H1"),
        PlaybookStep(3, "Entry Trigger", "M15 FVG + M1 MSS.", "M15"),
        PlaybookStep(4, "Execute", "Enter with 1:2 target.", "M1")
    ]

    def on_start(self):
        self.state = "MONITOR"

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []