"""
Strategy 06: Fractal-Based Inversion & Order Flow Strategy
Source: Faiz SMC ("The Only Trading Strategy I'd Use If I Had To Start Over")
Video URL: https://www.youtube.com/watch?v=YGKTvqJIx1w
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.structure import detect_swing_highs, detect_swing_lows, is_bullish_orderflow, is_bearish_orderflow
from backtester.indicators.fvg import detect_fvg, detect_ifvg, get_unmitigated_fvgs
from .base import BaseStrategy


class FractalInversionOrderflow(BaseStrategy):
    id = "s006_fractal_inversion_orderflow"
    name = "Fractal Inversion & Order Flow"
    source_video = "https://www.youtube.com/watch?v=YGKTvqJIx1w"
    description = "Higher timeframe orderflow + lower timeframe FVG inversion. Trade after 9:30 AM NY."
    timeframes = [TF.H1, TF.M15, TF.M5, TF.M1]
    
    playbook = [
        PlaybookStep(1, "H1 Orderflow", "Evaluate 1H chart for macro momentum. Bullish = respects bullish FVGs.", "H1"),
        PlaybookStep(2, "Macro Draw on Liquidity", "Identify H4/Daily equal highs/lows as target zones.", "H4"),
        PlaybookStep(3, "M15 FVG Formation", "Wait for fresh M15 FVG after 9:30 AM NY aligned with macro target.", "M15"),
        PlaybookStep(4, "M1 Inversion Confirmation", "Drop to 1-minute. Wait for IFVG (FVG inversion) + MSS confirmation.", "M1"),
        PlaybookStep(5, "Execute Entry", "Enter on close above/below inverted FVG. SL below/above swing.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_H1_BIAS"
        self.bias = None
        self.target_zone = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        h1_bar = bars.get(TF.H1)
        m15_bar = bars.get(TF.M15)
        m1_bar = bars.get(TF.M1)
        
        if not m1_bar:
            return []

        ny_time = get_ny_time(current_time)
        
        # Only trade after 9:30 AM NY
        if ny_time.hour < 9 or (ny_time.hour == 9 and ny_time.minute < 30):
            return []

        # Step 1: H1 Orderflow Bias
        if self.state == "WAIT_H1_BIAS":
            h1_hist = history(self.symbol, TF.H1, 30)
            if h1_hist:
                if is_bullish_orderflow(h1_hist):
                    self.bias = "bullish"
                    self.state = "WAIT_M15_FVG"
                elif is_bearish_orderflow(h1_hist):
                    self.bias = "bearish"
                    self.state = "WAIT_M15_FVG"

        # Step 2: Monitor for macro target zones
        elif self.state == "WAIT_M15_FVG":
            h4_hist = history(self.symbol, TF.H4, 50)
            if h4_hist:
                if self.bias == "bearish":
                    sw_highs = detect_swing_highs(h4_hist, lookback=3)
                    if sw_highs:
                        self.target_zone = max([s.price for s in sw_highs[-3:]])
                else:
                    sw_lows = detect_swing_lows(h4_hist, lookback=3)
                    if sw_lows:
                        self.target_zone = min([s.price for s in sw_lows[-3:]])

        # Step 3 & 4: M15 FVG and M1 Inversion
        if self.state == "WAIT_M15_FVG" and m15_bar:
            m15_hist = history(self.symbol, TF.M15, 30)
            fvgs = get_unmitigated_fvgs(detect_fvg(m15_hist, min_gap_pips=1.0))
            
            # Find FVG near target zone
            target_fvg = None
            for fvg in fvgs:
                if self.bias == "bearish" and fvg.direction == "bearish":
                    if self.target_zone and abs(fvg.high - self.target_zone) < (self.target_zone * 0.002):
                        target_fvg = fvg
                        break
                elif self.bias == "bullish" and fvg.direction == "bullish":
                    if self.target_zone and abs(fvg.low - self.target_zone) < (self.target_zone * 0.002):
                        target_fvg = fvg
                        break
            
            if target_fvg:
                self.active_fvg = target_fvg
                self.state = "WAIT_INVERSION"
                self.step_tracker.record(
                    "M15 FVG Found", 3, current_time, m15_bar.close, "M15",
                    f"FVG identified near target zone {self.target_zone:.5f}"
                )

        # Step 4: Wait for M1 Inversion
        elif self.state == "WAIT_INVERSION":
            m1_hist = history(self.symbol, TF.M1, 20)
            ifvgs = detect_ifvg(m1_hist)
            
            # Check for valid inversion
            for ifvg in ifvgs:
                if self.bias == "bearish" and ifvg.direction == "bearish":
                    # Bearish FVG inverted = bearish confirmation
                    if m1_bar.close < ifvg.low:
                        self.state = "DONE"
                        self.step_tracker.record(
                            "Inversion Confirmed", 4, current_time, m1_bar.close, "M1",
                            "M1 FVG inverted - executing short"
                        )
                        sl = m1_bar.high + (m1_bar.high * 0.0001)
                        if self.target_zone:
                            tp = self.target_zone
                        else:
                            tp = m1_bar.close - (m1_bar.close - sl) * 2
                        return [Signal(self.id, Direction.SHORT, m1_bar.close, sl, tp, current_time, self.symbol)]
                        
                elif self.bias == "bullish" and ifvg.direction == "bullish":
                    if m1_bar.close > ifvg.high:
                        self.state = "DONE"
                        self.step_tracker.record(
                            "Inversion Confirmed", 4, current_time, m1_bar.close, "M1",
                            "M1 FVG inverted - executing long"
                        )
                        sl = m1_bar.low - (m1_bar.low * 0.0001)
                        if self.target_zone:
                            tp = self.target_zone
                        else:
                            tp = m1_bar.close + (sl - m1_bar.close) * 2
                        return [Signal(self.id, Direction.LONG, m1_bar.close, sl, tp, current_time, self.symbol)]

        return []