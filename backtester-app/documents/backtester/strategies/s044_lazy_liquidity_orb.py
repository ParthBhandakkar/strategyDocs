"""
Strategy 44: The Lazy Liquidity Strategy (Mechanical ORB Setup)
Source: Faiz SMC ("The Laziest Liquidity Trading Strategy Making $15,000/Month")
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, Position, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from .base import BaseStrategy


class LazyLiquidityORB(BaseStrategy):
    id = "s044_lazy_liquidity_orb"
    name = "The Lazy Liquidity ORB"
    source_video = "https://www.youtube.com/watch?v=YKbkZ4eRd04"
    description = "A mechanical Opening Range Breakout strategy focusing on the 3:00 AM NY (London Open) 15-minute candle. Trades a body breakout of this range with a fixed 1:2 Risk/Reward."
    timeframes = [TF.M15]
    
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Isolate 3:00 AM Anchor Candle",
            description="Identify the 15-minute candle that prints exactly at 3:00 AM (London Open). Mark its absolute high and low.",
            timeframe="M15",
            conditions=["Time == 03:00 AM NY"]
        ),
        PlaybookStep(
            step_number=2,
            title="Await Confirmed Body Breakout",
            description="Wait for a subsequent 15-minute candle to close completely outside the anchor range. Wicks do not count.",
            timeframe="M15",
            conditions=["Candle Close > Anchor High OR Candle Close < Anchor Low"]
        ),
        PlaybookStep(
            step_number=3,
            title="Execute Entry",
            description="Enter aggressively at the close of the breakout candle.",
            timeframe="M15",
            conditions=["Execute Market Order immediately"]
        ),
        PlaybookStep(
            step_number=4,
            title="Set Risk Parameters",
            description="Set Stop Loss at the opposite side of the 3:00 AM anchor candle. Set Take Profit at a strict 1:2 RR.",
            timeframe="M15"
        ),
        PlaybookStep(
            step_number=5,
            title="Break-Even Protection",
            description="Move Stop Loss to entry price exactly when price reaches a 1:1 risk-to-reward ratio.",
            timeframe="M15"
        )
    ]

    def on_start(self):
        self.anchor_high = 0.0
        self.anchor_low = 0.0
        self.anchor_date = None
        self.trade_taken_today = False
        # Store state for "oco reversal exception" (failed breakout -> opposite breakout)
        self.last_trade_result = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        bar = bars.get(TF.M15)
        if not bar:
            return []

        ny_time = get_ny_time(bar.time)
        
        # Reset state on a new day
        if self.anchor_date != ny_time.date() and ny_time.hour == 0:
            self.anchor_high = 0.0
            self.anchor_low = 0.0
            self.trade_taken_today = False
            self.last_trade_result = None

        # 1. Capture the 3:00 AM candle (London Open)
        if ny_time.hour == 3 and ny_time.minute == 0:
            self.anchor_high = bar.high
            self.anchor_low = bar.low
            self.anchor_date = ny_time.date()
            self.step_tracker.record(
                "Isolate Anchor", 1, bar.time, bar.close, "M15",
                f"3:00 AM anchor established. High: {self.anchor_high:.5f}, Low: {self.anchor_low:.5f}"
            )
            return []

        # If we have an anchor and haven't hit our daily max limit
        if self.anchor_high > 0 and not self.trade_taken_today:
            
            # 2. Check for Bullish Breakout (close > anchor_high)
            if bar.close > self.anchor_high:
                sl = self.anchor_low
                risk = bar.close - sl
                if risk <= 0: return []
                tp = bar.close + (risk * 2)  # 1:2 RR
                
                self.step_tracker.record(
                    "Bullish Breakout", 2, bar.time, bar.close, "M15",
                    "Body closed above anchor high."
                )
                self.trade_taken_today = True
                
                return [Signal(
                    strategy_id=self.id,
                    direction=Direction.LONG,
                    entry_price=bar.close,
                    stop_loss=sl,
                    take_profit=tp,
                    timestamp=bar.time,
                    symbol=self.symbol,
                )]
                
            # 2. Check for Bearish Breakout (close < anchor_low)
            elif bar.close < self.anchor_low:
                sl = self.anchor_high
                risk = sl - bar.close
                if risk <= 0: return []
                tp = bar.close - (risk * 2)  # 1:2 RR
                
                self.step_tracker.record(
                    "Bearish Breakout", 2, bar.time, bar.close, "M15",
                    "Body closed below anchor low."
                )
                self.trade_taken_today = True
                
                return [Signal(
                    strategy_id=self.id,
                    direction=Direction.SHORT,
                    entry_price=bar.close,
                    stop_loss=sl,
                    take_profit=tp,
                    timestamp=bar.time,
                    symbol=self.symbol,
                )]
                
        return []

    def on_position_update(
        self,
        bars: dict[TF, Bar],
        history: callable,
        position: Position,
        broker,
        step_tracker,
        current_time: datetime,
    ):
        """Implement Break-Even rule at 1:1 RR."""
        if position.break_even_applied:
            return
            
        bar = bars.get(TF.M15)
        if not bar: return
        
        trade = position.trade
        risk = abs(trade.entry_price - trade.stop_loss)
        
        if trade.direction == Direction.LONG:
            target_1_1 = trade.entry_price + risk
            if bar.high >= target_1_1:
                broker.move_to_breakeven(self.id, bar, step_tracker)
        else:
            target_1_1 = trade.entry_price - risk
            if bar.low <= target_1_1:
                broker.move_to_breakeven(self.id, bar, step_tracker)
