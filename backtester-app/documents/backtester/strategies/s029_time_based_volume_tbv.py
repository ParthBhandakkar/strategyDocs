"""
Strategy 29: Time-Based Volume (TBV) Core Strategy
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from .base import BaseStrategy


class TimeBasedVolumeTBV(BaseStrategy):
    id = "s029_time_based_volume_tbv"
    name = "Time-Based Volume (TBV)"
    source_video = ""
    description = "Uses time-based volume analysis at specific NY times for entry signals."
    timeframes = [TF.M15, TF.M5, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Key Times", "Monitor 9:30 AM, 10:00 AM, 11:00 AM NY.", "M15"),
        PlaybookStep(2, "Volume Spike", "Look for high volume candles at key times.", "M15"),
        PlaybookStep(3, "Confirmation", "Wait for retest of high volume zone.", "M15"),
        PlaybookStep(4, "Execute", "Enter on M1 retest with tight SL.", "M1")
    ]

    def on_start(self):
        self.state = "MONITOR"
        self.key_times = [9, 10, 11, 13, 14, 15]

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        m15_bar = bars.get(TF.M15)
        if not m15_bar:
            return []

        ny_time = get_ny_time(current_time)
        
        if ny_time.hour in self.key_times and ny_time.minute == 0:
            m15_hist = history(self.symbol, TF.M15, 20)
            if m15_hist and len(m15_hist) > 5:
                avg_vol = sum(b.tick_volume for b in m15_hist[-5:]) / 5
                if m15_bar.tick_volume > avg_vol * 1.5:
                    self.high_vol_price = m15_bar.close
                    self.step_tracker.record("TBV Signal", 1, current_time, 
                        m15_bar.close, "M15", f"Vol: {m15_bar.tick_volume/avg_vol:.1f}x")

        return []