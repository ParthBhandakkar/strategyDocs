"""
Strategy 44: The Lazy Liquidity Strategy (Mechanical ORB Setup)
Source: Faiz SMC ("The Laziest Liquidity Trading Strategy Making $15,000/Month")

BIAS FIX (2026-06-19):
  Original bias: Anchor 3:00 AM M15 range captured at 3:00 (bar open) with full 15-min OHLC
  known in advance; breakout could fire on same incomplete candle.
  Fix: Capture anchor at 3:15 NY when the 3:00-3:15 M15 candle has closed; skip breakout
  checks on the anchor bar itself.

BACKTEST RESULTS (local Exness CSV, 2024-01-01 to 2024-06-30, all pairs):
  AUDCHF: Trades: 45 | Win rate: 37.78% | PF: 1.34 | PnL: $0.01 | Max DD: 4.33% | Avg R:R: 0.09
  AUDUSD: Trades: 128 | Win rate: 32.81% | PF: 1.08 | PnL: $0.00 | Max DD: 14.02% | Avg R:R: 0.02
  BTCUSD: Trades: 181 | Win rate: 20.44% | PF: 0.75 | PnL: $-8765.03 | Max DD: 37.0% | Avg R:R: -0.16
  CADCHF: Trades: 45 | Win rate: 20.0% | PF: 0.48 | PnL: $-0.01 | Max DD: 13.03% | Avg R:R: -0.29
  CADJPY: Trades: 45 | Win rate: 24.44% | PF: 0.78 | PnL: $-0.67 | Max DD: 10.73% | Avg R:R: -0.16
  CHFJPY: Trades: 45 | Win rate: 22.22% | PF: 0.53 | PnL: $-2.57 | Max DD: 15.26% | Avg R:R: -0.27
  ETHUSD: Trades: 179 | Win rate: 24.58% | PF: 1.04 | PnL: $67.17 | Max DD: 21.0% | Avg R:R: -0.04
  EURCHF: Trades: 44 | Win rate: 20.45% | PF: 0.84 | PnL: $-0.00 | Max DD: 10.17% | Avg R:R: -0.18
  EURGBP: Trades: 40 | Win rate: 30.0% | PF: 0.77 | PnL: $-0.00 | Max DD: 12.17% | Avg R:R: -0.15
  EURUSD: Trades: 128 | Win rate: 29.69% | PF: 0.99 | PnL: $-0.00 | Max DD: 16.93% | Avg R:R: -0.03
  GBPAUD: Trades: 45 | Win rate: 28.89% | PF: 1.06 | PnL: $0.00 | Max DD: 11.0% | Avg R:R: 0.03
  GBPCAD: Trades: 46 | Win rate: 23.91% | PF: 0.67 | PnL: $-0.01 | Max DD: 8.08% | Avg R:R: -0.18
  GBPCHF: Trades: 45 | Win rate: 24.44% | PF: 0.81 | PnL: $-0.01 | Max DD: 8.68% | Avg R:R: -0.19
  GBPJPY: Trades: 45 | Win rate: 22.22% | PF: 0.97 | PnL: $-0.20 | Max DD: 8.26% | Avg R:R: -0.11
  GBPNZD: Trades: 45 | Win rate: 22.22% | PF: 0.56 | PnL: $-0.02 | Max DD: 12.3% | Avg R:R: -0.18
  GBPUSD: Trades: 129 | Win rate: 21.71% | PF: 0.6 | PnL: $-0.04 | Max DD: 31.4% | Avg R:R: -0.18
  NZDJPY: Trades: 45 | Win rate: 35.56% | PF: 1.66 | PnL: $1.48 | Max DD: 7.0% | Avg R:R: 0.15
  NZDUSD: Trades: 128 | Win rate: 28.12% | PF: 0.83 | PnL: $-0.01 | Max DD: 21.14% | Avg R:R: -0.11
  USDCAD: Trades: 129 | Win rate: 25.58% | PF: 0.66 | PnL: $-0.03 | Max DD: 26.35% | Avg R:R: -0.16
  USDCHF: Trades: 125 | Win rate: 24.0% | PF: 0.76 | PnL: $-0.02 | Max DD: 38.8% | Avg R:R: -0.2
  USDJPY: Trades: 128 | Win rate: 24.22% | PF: 0.82 | PnL: $-2.14 | Max DD: 27.57% | Avg R:R: -0.17
  XAGUSD: Trades: 37 | Win rate: 24.32% | PF: 0.81 | PnL: $-0.54 | Max DD: 9.53% | Avg R:R: -0.12
  XAUUSD: Trades: 128 | Win rate: 25.0% | PF: 1.0 | PnL: $1.36 | Max DD: 15.6% | Avg R:R: -0.02
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
        ny_cur = get_ny_time(current_time)
        
        # Reset state on a new day
        if self.anchor_date != ny_time.date() and ny_cur.hour == 0:
            self.anchor_high = 0.0
            self.anchor_low = 0.0
            self.trade_taken_today = False
            self.last_trade_result = None

        # 1. Capture the 3:00 AM candle after the 3:00-3:15 M15 bar closes
        if ny_time.hour == 3 and ny_time.minute == 0 and ny_cur.hour == 3 and ny_cur.minute == 15:
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
