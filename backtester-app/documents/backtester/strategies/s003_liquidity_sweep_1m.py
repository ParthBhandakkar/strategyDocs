"""
Strategy 03: One-Minute Liquidity Sweep Trading Strategy
Source: Faiz SMC ("Secret ICT Liquidity Sweep Trading Strategy With Insane Winrate!")
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, Position, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.structure import detect_swing_highs, detect_swing_lows, detect_mss, is_bullish_orderflow, is_bearish_orderflow
from .base import BaseStrategy


class OneMinLiquiditySweep(BaseStrategy):
    id = "s003_liquidity_sweep_1m"
    name = "1M Liquidity Sweep (Three-Strike)"
    source_video = "https://www.youtube.com/watch?v=FAiYE-2zESk"
    description = "Uses 15M orderflow and H1 Draws on Liquidity. On M1, maps a structural range. Waits for price to sweep one boundary, then print an MSS/CISD back inside the range to enter."
    timeframes = [TF.H1, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Orderflow Direction", "Determine dominant orderflow on M15. Must respect FVGs.", "M15"),
        PlaybookStep(2, "Draw on Liquidity", "Locate major H1 structural pools (Session H/L, Daily H/L).", "H1"),
        PlaybookStep(3, "Execution Window", "Trade strictly between 09:30 AM and 2:00 PM NY Time.", "M1"),
        PlaybookStep(4, "Map 1M Range", "Map internal fractal sequence. Wait for MSS to lock in Range High and Range Low.", "M1"),
        PlaybookStep(5, "Wait for Boundary Sweep", "Price must sweep Range High (for shorts) without breaking Range Low first.", "M1"),
        PlaybookStep(6, "Execute on CISD", "Enter on a CISD closing back inside the range boundaries.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_M15_BIAS"
        self.bias = None
        self.range_high = 0.0
        self.range_low = 0.0
        self.sweep_extreme = 0.0
        self.trade_taken_today = False
        self.trade_date = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1_bar = bars.get(TF.M1)
        if not m1_bar:
            return []

        ny_time = get_ny_time(current_time)
        
        if self.trade_date != ny_time.date() and ny_time.hour == 0:
            self.on_start()
            self.trade_date = ny_time.date()

        # Step 3: Execution Window check
        if not is_in_session(current_time, "ny_am") and not is_in_session(current_time, "ny_pm"):
            self.state = "WAIT_M15_BIAS"
            return []

        if self.trade_taken_today:
            return []

        # Step 1: Check Bias dynamically
        m15_hist = history(self.symbol, TF.M15, 30)
        if self.state == "WAIT_M15_BIAS" and m15_hist:
            if is_bullish_orderflow(m15_hist):
                self.bias = "bullish"
                self.state = "MAP_RANGE"
            elif is_bearish_orderflow(m15_hist):
                self.bias = "bearish"
                self.state = "MAP_RANGE"

        # Step 4: Map 1M Range
        elif self.state == "MAP_RANGE":
            m1_hist = history(self.symbol, TF.M1, 60)
            shifts = detect_mss(m1_hist, lookback=3)
            
            if shifts:
                latest_shift = shifts[-1]
                # Lock in range based on recent structure
                sw_highs = detect_swing_highs(m1_hist, lookback=3)
                sw_lows = detect_swing_lows(m1_hist, lookback=3)
                
                if self.bias == "bearish" and latest_shift.direction == "bearish":
                    self.range_high = latest_shift.broken_level  # Approximated
                    self.range_low = min([s.price for s in sw_lows[-3:]]) if sw_lows else m1_bar.low
                    self.state = "WAIT_SWEEP"
                    self.step_tracker.record(
                        "Map Range", 4, current_time, self.range_high, "M1",
                        f"Mapped bearish range. High: {self.range_high:.5f}, Low: {self.range_low:.5f}"
                    )
                    
                elif self.bias == "bullish" and latest_shift.direction == "bullish":
                    self.range_low = latest_shift.broken_level
                    self.range_high = max([s.price for s in sw_highs[-3:]]) if sw_highs else m1_bar.high
                    self.state = "WAIT_SWEEP"
                    self.step_tracker.record(
                        "Map Range", 4, current_time, self.range_low, "M1",
                        f"Mapped bullish range. High: {self.range_high:.5f}, Low: {self.range_low:.5f}"
                    )

        # Step 5: Wait for Sweep (Three-Strike)
        elif self.state == "WAIT_SWEEP":
            if self.bias == "bearish":
                if m1_bar.low < self.range_low:
                    # Invalidated! Swept the wrong side first
                    self.state = "WAIT_M15_BIAS"
                elif m1_bar.high > self.range_high:
                    self.state = "WAIT_CISD"
                    self.sweep_extreme = m1_bar.high
                    
            elif self.bias == "bullish":
                if m1_bar.high > self.range_high:
                    self.state = "WAIT_M15_BIAS"
                elif m1_bar.low < self.range_low:
                    self.state = "WAIT_CISD"
                    self.sweep_extreme = m1_bar.low

        # Step 6: Execute on CISD
        elif self.state == "WAIT_CISD":
            if self.bias == "bearish":
                self.sweep_extreme = max(self.sweep_extreme, m1_bar.high)
                # CISD: Solid bearish candle closing back below Range High
                if m1_bar.is_bearish and m1_bar.close < self.range_high:
                    self.state = "DONE"
                    self.trade_taken_today = True
                    self.step_tracker.record(
                        "CISD Entry", 6, current_time, m1_bar.close, "M1",
                        "Bearish CISD confirmed back inside range."
                    )
                    sl = self.sweep_extreme + (self.sweep_extreme * 0.0001)
                    # Target 0.75 of range or Range Low
                    tp = self.range_low
                    return [Signal(self.id, Direction.SHORT, m1_bar.close, sl, tp, current_time, self.symbol)]
                    
            elif self.bias == "bullish":
                self.sweep_extreme = min(self.sweep_extreme, m1_bar.low)
                if m1_bar.is_bullish and m1_bar.close > self.range_low:
                    self.state = "DONE"
                    self.trade_taken_today = True
                    self.step_tracker.record(
                        "CISD Entry", 6, current_time, m1_bar.close, "M1",
                        "Bullish CISD confirmed back inside range."
                    )
                    sl = self.sweep_extreme - (self.sweep_extreme * 0.0001)
                    tp = self.range_high
                    return [Signal(self.id, Direction.LONG, m1_bar.close, sl, tp, current_time, self.symbol)]

        return []

    def on_position_update(self, bars, history, position, broker, step_tracker, current_time):
        """Move to BE when hitting opposite range boundary."""
        if position.break_even_applied:
            return
            
        m1_bar = bars.get(TF.M1)
        if not m1_bar: return
        
        trade = position.trade
        # The strategy says: once price completely clears the opposite boundary, move to BE.
        if trade.direction == Direction.SHORT and m1_bar.low <= self.range_low:
            broker.move_to_breakeven(self.id, m1_bar, step_tracker)
        elif trade.direction == Direction.LONG and m1_bar.high >= self.range_high:
            broker.move_to_breakeven(self.id, m1_bar, step_tracker)
