"""
Strategy 17: The 1H Pattern Nobody Talks About
Source: Faiz SMC ("The 1H Pattern Nobody Talks About")
Video URL: https://www.youtube.com/watch?v=some_id
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.structure import detect_swing_highs, detect_swing_lows, detect_mss
from .base import BaseStrategy


class OneHPattern(BaseStrategy):
    id = "s017_1h_pattern"
    name = "1H Pattern Strategy"
    source_video = ""
    description = "Uses the 1-hour chart pattern for swing trades. Monitors H1 swing points and M1 entries."
    timeframes = [TF.H1, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Identify H1 Pattern", "Find clean H1 swing high/low sequence.", "H1"),
        PlaybookStep(2, "Wait for Break", "Price must break recent H1 swing with momentum.", "H1"),
        PlaybookStep(3, "M15 Confirmation", "Confirm on M15 with FVG or OB.", "M15"),
        PlaybookStep(4, "Execute M1", "Enter on M1 MSS retest.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_PATTERN"
        self.last_swing_high = 0.0
        self.last_swing_low = 0.0

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        h1_bar = bars.get(TF.H1)
        if not h1_bar:
            return []

        if self.state == "WAIT_PATTERN":
            h1_hist = history(self.symbol, TF.H1, 50)
            if h1_hist:
                sw_highs = detect_swing_highs(h1_hist)
                sw_lows = detect_swing_lows(h1_hist)
                
                if sw_highs:
                    self.last_swing_high = sw_highs[-1].price
                if sw_lows:
                    self.last_swing_low = sw_lows[-1].price
                    
                if sw_highs and sw_lows:
                    self.state = "MONITOR"
                    
        return []