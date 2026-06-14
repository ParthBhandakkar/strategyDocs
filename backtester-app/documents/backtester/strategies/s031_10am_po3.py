"""
Strategy 31: One Trading Setup For Life - ICT 10AM PO3
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.amd import detect_candle_open_price
from backtester.indicators.fibonacci import get_sd_target
from .base import BaseStrategy


class TenAMPO3(BaseStrategy):
    id = "s031_10am_po3"
    name = "10AM PO3 Setup"
    source_video = ""
    description = "Uses 10:00 AM NY 4-hour candle open for PO3 entry. Targets -2.0 SD."
    timeframes = [TF.H4, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "10AM Open", "Mark 10:00 AM H4 open price.", "H4"),
        PlaybookStep(2, "Manipulation", "Wait for price to cross the open.", "M15"),
        PlaybookStep(3, "MSS", "Wait for M15 MSS back through open.", "M15"),
        PlaybookStep(4, "SD Target", "Enter on M1, target -2.0 SD.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_10AM"
        self.open_10am = 0.0

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        h4_bar = bars.get(TF.H4)
        m1_bar = bars.get(TF.M1)
        if not m1_bar:
            return []

        ny_time = get_ny_time(current_time)
        
        # Capture 10AM H4 open
        if self.state == "WAIT_10AM" and h4_bar:
            ny_h4 = get_ny_time(h4_bar.time)
            if ny_h4.hour >= 10 and ny_h4.hour < 14:
                self.open_10am = h4_bar.open
                self.state = "WAIT_MANIPULATION"
                self.step_tracker.record("10AM Open", 1, current_time, self.open_10am, "H4", 
                    f"10AM H4 open: {self.open_10am:.5f}")

        return []