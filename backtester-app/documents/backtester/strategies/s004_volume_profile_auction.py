"""
Strategy 04: Gold Fixed Range Volume Profile
Source: Faiz SMC ("The Easiest Gold Volume Profile Trading Strategy That Works!")
Video URL: https://www.youtube.com/watch?v=LsC2IokcYpc
"""

from __future__ import annotations
from datetime import datetime, time, timedelta

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.volume_profile import compute_frvp
from .base import BaseStrategy


class GoldFixedRangeVolumeProfile(BaseStrategy):
    id = "s004_volume_profile_auction"
    name = "Gold Fixed Range Volume Profile"
    source_video = "https://www.youtube.com/watch?v=LsC2IokcYpc"
    description = "Uses 5-minute Fixed Range Volume Profile on London session (3AM-7AM NY). Trades failed auctions at Value Area boundaries."
    timeframes = [TF.M5]
    
    playbook = [
        PlaybookStep(1, "Draw FRVP", "Draw Fixed Range Volume Profile from 3:00 AM to 7:00 AM NY Time.", "M5"),
        PlaybookStep(2, "Identify Shape", "Determine profile shape: D (balanced), P (bullish), B (bearish).", "M5"),
        PlaybookStep(3, "Wait for Breakout", "After 7AM, wait for price to break and close outside VAH or VAL.", "M5"),
        PlaybookStep(4, "Failed Auction Entry", "Wait for price to reclaim back inside the Value Area. Enter on reclaim close.", "M5"),
        PlaybookStep(5, "Target POC", "Take profit at POC or opposite VA boundary.", "M5")
    ]

    def on_start(self):
        self.state = "WAIT_SESSION"
        self.frvp = None
        self.vah = 0.0
        self.val = 0.0
        self.poc = 0.0
        self.breakout_direction = None
        self.trade_today = False
        self.trade_date = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m5_bar = bars.get(TF.M5)
        if not m5_bar:
            return []

        ny_time = get_ny_time(current_time)
        
        # Reset daily state
        if self.trade_date != ny_time.date() and ny_time.hour == 0:
            self.on_start()
            self.trade_date = ny_time.date()

        # Check if we're in London session for FRVP drawing
        if self.state == "WAIT_SESSION":
            if is_in_session(current_time, "london"):
                # Start collecting bars for FRVP
                self.state = "COLLECT_SESSION"
                self.session_start_time = current_time

        # Step 1: Collect London session bars and compute FRVP at 7AM
        elif self.state == "COLLECT_SESSION":
            # At exactly 7AM close, compute the FRVP
            if ny_time.hour == 7 and ny_time.minute == 0:
                # Get bars from 3AM to 7AM
                session_start = ny_time.replace(hour=3, minute=0, second=0, microsecond=0)
                session_end = ny_time.replace(hour=7, minute=0, second=0, microsecond=0)
                
                m5_hist = history(self.symbol, TF.M5, 100)
                session_bars = [b for b in m5_hist if get_ny_time(b.time) >= session_start and get_ny_time(b.time) <= session_end]
                
                if session_bars:
                    self.frvp = compute_frvp(session_bars, row_size=100)
                    if self.frvp:
                        self.vah = self.frvp.vah
                        self.val = self.frvp.val
                        self.poc = self.frvp.poc
                        self.state = "WAIT_BREAKOUT"
                        self.step_tracker.record(
                            "FRVP Computed", 1, current_time, self.poc, "M5",
                            f"VAH: {self.vah:.5f}, VAL: {self.val:.5f}, POC: {self.poc:.5f}"
                        )

        # Step 3: Wait for breakout outside Value Area
        elif self.state == "WAIT_BREAKOUT":
            if self.trade_today:
                return []
            
            # Check for breakout above VAH
            if m5_bar.close > self.vah:
                self.breakout_direction = "bullish"
                self.state = "WAIT_RECLAIM"
                self.step_tracker.record(
                    "Breakout Up", 3, current_time, m5_bar.close, "M5",
                    f"Price broke above VAH at {self.vah:.5f}"
                )
                
            # Check for breakout below VAL
            elif m5_bar.close < self.val:
                self.breakout_direction = "bearish"
                self.state = "WAIT_RECLAIM"
                self.step_tracker.record(
                    "Breakout Down", 3, current_time, m5_bar.close, "M5",
                    f"Price broke below VAL at {self.val:.5f}"
                )

        # Step 4: Wait for Failed Auction Reclaim
        elif self.state == "WAIT_RECLAIM":
            if self.trade_today:
                return []
                
            if self.breakout_direction == "bearish":
                # Price broke down, wait for reclaim above VAL (long entry)
                if m5_bar.close > self.val and m5_bar.low <= self.val:
                    self.state = "DONE"
                    self.trade_today = True
                    self.step_tracker.record(
                        "Failed Auction Long", 4, current_time, m5_bar.close, "M5",
                        "Price reclaimed VAL after breaking below - LONG entry"
                    )
                    sl = m5_bar.low - (m5_bar.low * 0.0001)
                    tp = self.poc
                    return [Signal(self.id, Direction.LONG, m5_bar.close, sl, tp, current_time, self.symbol)]
                    
            elif self.breakout_direction == "bullish":
                # Price broke up, wait for reclaim below VAH (short entry)
                if m5_bar.close < self.vah and m5_bar.high >= self.vah:
                    self.state = "DONE"
                    self.trade_today = True
                    self.step_tracker.record(
                        "Failed Auction Short", 4, current_time, m5_bar.close, "M5",
                        "Price reclaimed VAH after breaking above - SHORT entry"
                    )
                    sl = m5_bar.high + (m5_bar.high * 0.0001)
                    tp = self.poc
                    return [Signal(self.id, Direction.SHORT, m5_bar.close, sl, tp, current_time, self.symbol)]

        return []

    def on_position_update(self, bars, history, position, broker, step_tracker, current_time):
        """Move to BE at POC."""
        if position.break_even_applied:
            return
            
        m5_bar = bars.get(TF.M5)
        if not m5_bar: return
        
        trade = position.trade
        # Move to BE when hitting POC
        if trade.direction == Direction.LONG and m5_bar.high >= self.poc:
            broker.move_to_breakeven(self.id, m5_bar, step_tracker)
        elif trade.direction == Direction.SHORT and m5_bar.low <= self.poc:
            broker.move_to_breakeven(self.id, m5_bar, step_tracker)