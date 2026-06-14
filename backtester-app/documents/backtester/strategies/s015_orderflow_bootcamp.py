"""
Strategy 15: Orderflow Boot Camp - Lesson 1: Volume
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.structure import is_bullish_orderflow, is_bearish_orderflow
from .base import BaseStrategy


class OrderflowBootCamp(BaseStrategy):
    id = "s015_orderflow_bootcamp"
    name = "Orderflow Boot Camp L1"
    source_video = ""
    description = "Volume-based orderflow analysis. Uses tick volume to confirm institutional activity."
    timeframes = [TF.M15, TF.M5, TF.M1]
    
    playbook = [
        PlaybookStep(1, "High Volume Analysis", "Identify high volume candles as institutional footprints.", "M15"),
        PlaybookStep(2, "Confirm Direction", "Check if high volume candles align with trend.", "M15"),
        PlaybookStep(3, "Wait for Retest", "After high volume move, wait for retest of the zone.", "M15"),
        PlaybookStep(4, "Execute", "Enter on retest with tight SL.", "M1")
    ]

    def on_start(self):
        self.state = "MONITOR"
        self.high_volume_level = 0.0

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        m15_bar = bars.get(TF.M15)
        if not m15_bar:
            return []
        
        # Track high volume bars
        m15_hist = history(self.symbol, TF.M15, 30)
        if m15_hist:
            avg_vol = sum(b.tick_volume for b in m15_hist[-10:]) / 10
            if m15_bar.tick_volume > avg_vol * 1.5:
                self.high_volume_level = m15_bar.close
                self.step_tracker.record("High Volume", 1, current_time, m15_bar.close, "M15",
                    f"Volume {m15_bar.tick_volume/avg_vol:.1f}x average")
        
        return []