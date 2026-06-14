"""
Strategy 14: The 3-Step A ICT Gold Strategy
Source: Faiz SMC ("The 3-Step A ICT Gold Strategy")
Video URL: https://www.youtube.com/watch?v=some_id
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.structure import detect_mss, detect_swing_highs, detect_swing_lows
from .base import BaseStrategy


class ThreeStepAICTStrategy(BaseStrategy):
    id = "s014_3step_a_ict_gold"
    name = "3-Step A ICT Gold Strategy"
    source_video = ""
    description = "Three-step approach: Identify A) market structure, B) liquidity zones, C) entry trigger."
    timeframes = [TF.H1, TF.M15, TF.M5, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Market Structure (A)", "Identify H1 trend and orderflow direction.", "H1"),
        PlaybookStep(2, "Liquidity Zones (B)", "Map H4 swing highs/lows as liquidity targets.", "H4"),
        PlaybookStep(3, "Entry Trigger (C)", "Wait for M15 MSS inside FVG near liquidity.", "M15"),
        PlaybookStep(4, "Execute M1", "Confirm with M1 CISD and execute.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_BIAS"
        self.bias = None

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []