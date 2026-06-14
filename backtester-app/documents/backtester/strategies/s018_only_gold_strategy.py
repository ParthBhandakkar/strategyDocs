"""
Strategy 18: The Only GOLD Trading Strategy You Need
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.structure import detect_swing_highs, detect_swing_lows, detect_mss
from .base import BaseStrategy


class OnlyGoldStrategy(BaseStrategy):
    id = "s018_only_gold_strategy"
    name = "Only Gold Trading Strategy"
    source_video = ""
    description = "Gold-specific strategy using London session profile and NY session breakouts."
    timeframes = [TF.M5, TF.M1]
    
    playbook = [
        PlaybookStep(1, "London Profile", "Map London session (3AM-7AM NY) range.", "M5"),
        PlaybookStep(2, "NY Session Break", "Wait for price to break London range in NY session.", "M5"),
        PlaybookStep(3, "Retest Entry", "Enter on retest of broken range boundary.", "M1"),
        PlaybookStep(4, "Target", "Target 1:2 R with daily highs/lows.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_LONDON"
        self.london_high = 0.0
        self.london_low = 0.0

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        m5_bar = bars.get(TF.M5)
        if not m5_bar:
            return []

        ny_time = get_ny_time(current_time)
        
        # Capture London session
        if self.state == "WAIT_LONDON" and is_in_session(current_time, "london"):
            m5_hist = history(self.symbol, TF.M5, 50)
            london_bars = [b for b in m5_hist if 3 <= get_ny_time(b.time).hour < 7]
            if london_bars:
                self.london_high = max(b.high for b in london_bars)
                self.london_low = min(b.low for b in london_bars)
                self.state = "WAIT_BREAK"
                self.step_tracker.record("London Range", 1, current_time, 
                    (self.london_high + self.london_low)/2, "M5",
                    f"H: {self.london_high:.5f}, L: {self.london_low:.5f}")

        return []