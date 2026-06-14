"""
Strategy 26: Live Trading NQ - Inverse FVG Scalp Setup
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.fvg import detect_fvg, detect_ifvg
from backtester.indicators.structure import detect_mss
from .base import BaseStrategy


class InverseFVGScalp(BaseStrategy):
    id = "s026_inverse_fvg_scalp"
    name = "Inverse FVG Scalp (NQ)"
    source_video = ""
    description = "Scalp strategy using Inverted Fair Value Gaps on NQ futures during NY session."
    timeframes = [TF.M5, TF.M1]
    
    playbook = [
        PlaybookStep(1, "M5 FVG", "Identify M5 FVG after 9:30 AM NY.", "M5"),
        PlaybookStep(2, "Wait Inversion", "Wait for price to invert the FVG.", "M5"),
        PlaybookStep(3, "M1 Confirmation", "Confirm with M1 MSS.", "M1"),
        PlaybookStep(4, "Execute", "Enter on M1 close. Target 1:1.5.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_FVG"
        self.fvg_found = False

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        m5_bar = bars.get(TF.M5)
        m1_bar = bars.get(TF.M1)
        if not m1_bar:
            return []

        ny_time = get_ny_time(current_time)
        
        # Only after 9:30 AM NY
        if ny_time.hour < 9 or (ny_time.hour == 9 and ny_time.minute < 30):
            return []

        if self.state == "WAIT_FVG" and m5_bar:
            m5_hist = history(self.symbol, TF.M5, 30)
            fvgs = detect_fvg(m5_hist, min_gap_pips=1.0)
            if fvgs:
                self.active_fvg = fvgs[-1]
                self.state = "WAIT_INVERSION"
                self.step_tracker.record("FVG Found", 1, current_time, 
                    m5_bar.close, "M5", f"FVG: {self.active_fvg.direction}")

        elif self.state == "WAIT_INVERSION":
            m1_hist = history(self.symbol, TF.M1, 20)
            ifvgs = detect_ifvg(m1_hist)
            
            for ifvg in ifvgs:
                m1_hist_full = history(self.symbol, TF.M1, 30)
                shifts = detect_mss(m1_hist_full, lookback=2)
                
                if ifvg.direction == "bearish" and shifts:
                    for shift in shifts:
                        if shift.direction == "bearish" and m1_bar.close < ifvg.low:
                            self.state = "DONE"
                            sl = m1_bar.high + (m1_bar.high * 0.0001)
                            tp = m1_bar.close - (sl - m1_bar.close) * 1.5
                            return [Signal(self.id, Direction.SHORT, m1_bar.close, sl, tp, current_time, self.symbol)]
                            
                elif ifvg.direction == "bullish" and shifts:
                    for shift in shifts:
                        if shift.direction == "bullish" and m1_bar.close > ifvg.high:
                            self.state = "DONE"
                            sl = m1_bar.low - (m1_bar.low * 0.0001)
                            tp = m1_bar.close + (sl - m1_bar.close) * 1.5
                            return [Signal(self.id, Direction.LONG, m1_bar.close, sl, tp, current_time, self.symbol)]

        return []