"""
Strategy 27: The Power of 3 (AMD) Silver Bullet
Source: Faiz SMC ("This ICT Strategy Is Boring But It Made Me Profitable")
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, Position, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.amd import detect_candle_open_price
from backtester.indicators.fibonacci import get_sd_target
from backtester.indicators.structure import detect_mss, detect_swing_highs, detect_swing_lows
from .base import BaseStrategy


class PO3SilverBullet(BaseStrategy):
    id = "s027_po3_silver_bullet"
    name = "PO3 Silver Bullet (-2.0 SD)"
    source_video = "https://www.youtube.com/watch?v=exkANBItgUc"
    description = "Uses the 10:00 AM 4-Hour Candle open price to frame the Accumulation/Manipulation/Distribution cycle. Uses -1.0 Standard Deviation on M1 to confirm distribution, targets -2.0 SD."
    timeframes = [TF.H4, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Macro Selection", "Mark the Opening Price of the 10:00 AM NY 4-Hour candle exactly when it opens.", "H4"),
        PlaybookStep(2, "Context Shift", "Switch to 1-Minute timeframe at 10:00 AM and track price relative to open.", "M1"),
        PlaybookStep(3, "Manipulation Phase", "Wait for price to trade across the Opening Price line, forming clear structure.", "M1"),
        PlaybookStep(4, "Market Structure Shift", "Wait for price to aggressively shift structure.", "M1"),
        PlaybookStep(5, "Silver Bullet Confirmation", "Apply Fib from lowest/highest manipulation point to last swing. Candle must close past -1.0 SD.", "M1"),
        PlaybookStep(6, "Order Entry", "Frame limit order at nearest FVG. Invalid if price hits -2.0 SD before retrace.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_10AM"
        self.open_price_10am = 0.0
        self.manipulation_extreme = 0.0
        self.last_swing = 0.0
        self.sd_minus_1 = 0.0
        self.sd_minus_2 = 0.0
        self.direction = None
        self.trade_date = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1_bar = bars.get(TF.M1)
        if not m1_bar: return []

        ny_time = get_ny_time(current_time)
        
        if self.trade_date != ny_time.date() and ny_time.hour == 0:
            self.on_start()
            self.trade_date = ny_time.date()

        # Step 1: Capture 10:00 AM H4 Open
        if self.state == "WAIT_10AM" and ny_time.hour == 10 and ny_time.minute == 0:
            self.open_price_10am = m1_bar.open
            self.state = "WAIT_MANIPULATION"
            self.manipulation_extreme = self.open_price_10am
            self.step_tracker.record(
                "Macro Open", 1, current_time, self.open_price_10am, "H4",
                f"10AM Open Price anchored at {self.open_price_10am:.5f}"
            )
            return []

        # Step 3: Track Manipulation Phase
        if self.state == "WAIT_MANIPULATION":
            # Just track the extreme while we wait for an MSS
            if m1_bar.high > self.open_price_10am:
                self.manipulation_extreme = max(self.manipulation_extreme, m1_bar.high)
            if m1_bar.low < self.open_price_10am:
                self.manipulation_extreme = min(self.manipulation_extreme, m1_bar.low)
                
            m1_hist = history(self.symbol, TF.M1, 40)
            shifts = detect_mss(m1_hist, lookback=2)
            
            if shifts:
                shift = shifts[-1]
                # If we were manipulating ABOVE open, a bearish MSS suggests we're entering distribution (short)
                if shift.direction == "bearish" and self.manipulation_extreme > self.open_price_10am:
                    self.direction = "bearish"
                    self.last_swing = shift.broken_level
                    
                    self.sd_minus_1 = get_sd_target(self.manipulation_extreme, self.last_swing, -1.0, "bearish")
                    self.sd_minus_2 = get_sd_target(self.manipulation_extreme, self.last_swing, -2.0, "bearish")
                    
                    self.state = "WAIT_SD_CONFIRM"
                    self.step_tracker.record(
                        "Manipulation MSS", 4, current_time, m1_bar.close, "M1",
                        f"Bearish MSS detected. Waiting for close below -1.0 SD ({self.sd_minus_1:.5f})"
                    )
                    
                # If manipulating BELOW open, a bullish MSS suggests distribution (long)
                elif shift.direction == "bullish" and self.manipulation_extreme < self.open_price_10am:
                    self.direction = "bullish"
                    self.last_swing = shift.broken_level
                    
                    self.sd_minus_1 = get_sd_target(self.last_swing, self.manipulation_extreme, -1.0, "bullish")
                    self.sd_minus_2 = get_sd_target(self.last_swing, self.manipulation_extreme, -2.0, "bullish")
                    
                    self.state = "WAIT_SD_CONFIRM"
                    self.step_tracker.record(
                        "Manipulation MSS", 4, current_time, m1_bar.close, "M1",
                        f"Bullish MSS detected. Waiting for close above -1.0 SD ({self.sd_minus_1:.5f})"
                    )

        # Step 5: Wait for -1.0 SD Validation Close
        elif self.state == "WAIT_SD_CONFIRM":
            # Invalidated if it hits -2.0 before confirming and retracing
            if self.direction == "bearish" and m1_bar.low <= self.sd_minus_2:
                self.state = "DONE"
                return []
            if self.direction == "bullish" and m1_bar.high >= self.sd_minus_2:
                self.state = "DONE"
                return []

            if self.direction == "bearish" and m1_bar.close < self.sd_minus_1:
                self.state = "DONE"
                self.step_tracker.record(
                    "SD Confirmed", 5, current_time, m1_bar.close, "M1",
                    "Closed below -1.0 SD. Executing Short."
                )
                sl = self.manipulation_extreme + (self.manipulation_extreme * 0.0001)
                return [Signal(self.id, Direction.SHORT, m1_bar.close, sl, self.sd_minus_2, current_time, self.symbol)]
                
            elif self.direction == "bullish" and m1_bar.close > self.sd_minus_1:
                self.state = "DONE"
                self.step_tracker.record(
                    "SD Confirmed", 5, current_time, m1_bar.close, "M1",
                    "Closed above -1.0 SD. Executing Long."
                )
                sl = self.manipulation_extreme - (self.manipulation_extreme * 0.0001)
                return [Signal(self.id, Direction.LONG, m1_bar.close, sl, self.sd_minus_2, current_time, self.symbol)]

        return []
