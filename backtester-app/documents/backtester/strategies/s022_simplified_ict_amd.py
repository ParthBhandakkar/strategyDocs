"""
Strategy 22: Simplified ICT AMD Trading Strategy
Source: Faiz SMC ("I Simplified ICT AMD Trading Strategy")
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.amd import detect_candle_open_price
from backtester.indicators.structure import detect_mss
from .base import BaseStrategy


class SimplifiedICTAMD(BaseStrategy):
    id = "s022_simplified_ict_amd"
    name = "Simplified ICT AMD"
    source_video = ""
    description = "Uses Average Daily Range (ADR) andCandle Open Price fordaily bias and targets."
    timeframes = [TF.D1, TF.H4, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Daily Bias", "Mark D1 candle open as daily anchor.", "D1"),
        PlaybookStep(2, "ADR Calculation", "Calculate ADR from last 5-7 days.", "D1"),
        PlaybookStep(3, "H4 Structure", "Identify H4 swing points relative to D1 open.", "H4"),
        PlaybookStep(4, "M1 Entry", "Execute on M1 MSS at H4 level.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_D1"
        self.d1_open = 0.0
        self.adr = 0.0

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        d1_bar = bars.get(TF.D1)
        if not d1_bar:
            return []
            
        ny_time = get_ny_time(current_time)
        
        # Get daily open at session start
        if self.state == "WAIT_D1" and ny_time.hour == 0:
            self.d1_open = d1_bar.open
            d1_hist = history(self.symbol, TF.D1, 7)
            if d1_hist and len(d1_hist) >= 5:
                ranges = [b.high - b.low for b in d1_hist[-5:]]
                self.adr = sum(ranges) / len(ranges)
            self.state = "MONITOR"
            self.step_tracker.record("D1 Open", 1, current_time, self.d1_open, "D1",
                f"ADR: {self.adr:.5f}")
            
        return []