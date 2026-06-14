"""
Strategy 11: ICT Volume Profile Breakout
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.structure import is_bullish_orderflow, is_bearish_orderflow
from backtester.indicators.fvg import detect_fvg
from .base import BaseStrategy


class ICTVolumeProfileBreakout(BaseStrategy):
    id = "s011_ict_volume_profile_breakout"
    name = "ICT Volume Profile Breakout"
    source_video = ""
    description = "Uses ICT concepts with volume profile for breakout trading."
    timeframes = [TF.M15, TF.M5, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Market Bias", "Determine H1 bias using orderflow.", "H1"),
        PlaybookStep(2, "Volume Profile", "Map M15 volume profile for value areas.", "M15"),
        PlaybookStep(3, "Breakout Setup", "Wait for clean close outside profile.", "M15"),
        PlaybookStep(4, "Execute", "Enter on M1 retest.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_BIAS"
        self.bias = None

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []