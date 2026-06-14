"""
Strategy 05: Macro Volume Profile & ICT Concepts
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.structure import detect_swing_highs, detect_swing_lows
from .base import BaseStrategy


class MacroVolumeProfile(BaseStrategy):
    id = "s005_macro_volume_profile"
    name = "Macro Volume Profile & ICT"
    source_video = ""
    description = "Uses macro (H4/Daily) volume profile to identify institutional order flow and major liquidity zones."
    timeframes = [TF.H4, TF.D1, TF.M15]
    
    playbook = [
        PlaybookStep(1, "Daily Profile", "Map D1 or H4 volume profile for macro context.", "D1"),
        PlaybookStep(2, "Identify POC", "Mark the Point of Control as key institutional magnet.", "D1"),
        PlaybookStep(3, "Liquidity Sweeps", "Monitor for H4 liquidity sweeps into POC zone.", "H4"),
        PlaybookStep(4, "M15 Entry", "Execute on M15 MSS when price rejects from POC zone.", "M15")
    ]

    def on_start(self):
        self.state = "MONITOR"
        self.d1_poc = 0.0

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        d1_bar = bars.get(TF.D1)
        if not d1_bar:
            return []
            
        # Get daily profile context
        d1_hist = history(self.symbol, TF.D1, 20)
        if d1_hist and len(d1_hist) >= 10:
            # Simple POC approximation: use midpoint of recent range
            recent_high = max(b.high for b in d1_hist[-10:])
            recent_low = min(b.low for b in d1_hist[-10:])
            self.d1_poc = (recent_high + recent_low) / 2
            
        # Check for POC touches
        if d1_bar.low <= self.d1_poc <= d1_bar.high:
            self.step_tracker.record(
                "POC Touch", 2, current_time, self.d1_poc, "D1",
                f"Price touched POC at {self.d1_poc:.5f}"
            )
            
        return []