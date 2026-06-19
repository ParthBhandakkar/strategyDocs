"""
Strategy 12: The 8:00 AM Candle Strategy
Source: Faiz SMC ("This 8AM Candle Strategy Is Boring, But It Makes F*ck You Money")

BIAS FIX (2026-06-19):
  Original bias: Marked the 8:00 AM H1 range when h1_bar.hour==8 at the START of that hour,
  using the full hour's OHLC before the 8-9 AM candle closed (playbook requires close).
  Fix: Only capture the 8 AM H1 candle after 9:00 AM NY when that H1 bar is fully closed
  (relying on engine bar-close semantics + explicit ny_cur.hour >= 9 check).

BACKTEST RESULTS (local Exness CSV, 2024-01-01 to 2024-06-30, all pairs):
  AUDCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  AUDUSD: Trades: 59 | Win rate: 3.39% | PF: 0.19 | PnL: $-0.02 | Max DD: 20.74% | Avg R:R: -0.34
  BTCUSD: Trades: 122 | Win rate: 6.56% | PF: 0.31 | PnL: $-9340.53 | Max DD: 19.82% | Avg R:R: -0.16
  CADCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  CADJPY: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  CHFJPY: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  ETHUSD: Trades: 111 | Win rate: 5.41% | PF: 0.14 | PnL: $-746.56 | Max DD: 24.99% | Avg R:R: -0.22
  EURCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  EURGBP: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  EURUSD: Trades: 59 | Win rate: 8.47% | PF: 0.42 | PnL: $-0.01 | Max DD: 12.07% | Avg R:R: -0.18
  GBPAUD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPCAD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPJPY: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPNZD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPUSD: Trades: 57 | Win rate: 7.02% | PF: 0.36 | PnL: $-0.02 | Max DD: 12.92% | Avg R:R: -0.23
  NZDJPY: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  NZDUSD: Trades: 60 | Win rate: 8.33% | PF: 0.49 | PnL: $-0.01 | Max DD: 10.64% | Avg R:R: -0.09
  USDCAD: Trades: 49 | Win rate: 10.2% | PF: 0.37 | PnL: $-0.02 | Max DD: 13.45% | Avg R:R: -0.22
  USDCHF: Trades: 61 | Win rate: 6.56% | PF: 0.2 | PnL: $-0.02 | Max DD: 16.95% | Avg R:R: -0.28
  USDJPY: Trades: 74 | Win rate: 2.7% | PF: 0.17 | PnL: $-3.61 | Max DD: 24.2% | Avg R:R: -0.33
  XAGUSD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  XAUUSD: Trades: 67 | Win rate: 13.43% | PF: 0.69 | PnL: $-45.92 | Max DD: 14.46% | Avg R:R: -0.14
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, Position, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.structure import detect_mss, detect_swing_highs, detect_swing_lows
from .base import BaseStrategy


class EightAMCandleStrategy(BaseStrategy):
    id = "s012_8am_candle"
    name = "The 8:00 AM Candle Sweeps"
    source_video = "https://www.youtube.com/watch?v=2cuaTYjEw9Q"
    description = "Uses the 8:00 AM hourly candle boundaries to trap pre-market algorithms. Waits for a liquidity sweep of the 8AM H/L and an adjacent hourly swing point, followed by a 1-minute MSS."
    timeframes = [TF.H1, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Mark 8AM Boundary", "Wait for the 8:00 AM NY hourly candle to close. Mark its high and low wicks.", "H1"),
        PlaybookStep(2, "Identify Key Swing", "Find the nearest H1 swing high above the 8AM high, and nearest swing low below the 8AM low.", "H1"),
        PlaybookStep(3, "Wait for Sweep", "Wait for M1 price action to sweep past BOTH the 8AM boundary and the adjacent swing point.", "M1"),
        PlaybookStep(4, "Confirm Entry (MSS)", "Wait for a 1-minute Market Structure Shift (MSS) pushing price back inside the 8AM candle boundary.", "M1"),
        PlaybookStep(5, "Execute & Manage", "Enter market, place SL outside sweep wick. Target the 50% midpoint of the 8AM candle for partial/BE, and the opposite boundary for final TP.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_8AM"
        self.candle_8am_high = 0.0
        self.candle_8am_low = 0.0
        self.candle_8am_mid = 0.0
        self.target_swing_high = 0.0
        self.target_swing_low = 0.0
        
        self.sweep_direction = None # "high" or "low"
        self.sweep_extreme = 0.0
        
        self.trade_date = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        h1_bar = bars.get(TF.H1)
        m1_bar = bars.get(TF.M1)
        if not m1_bar:
            return []

        ny_time = get_ny_time(current_time)
        
        # Reset daily state
        if self.trade_date != ny_time.date() and ny_time.hour == 0:
            self.on_start()
            self.trade_date = ny_time.date()

        # Step 1: Capture 8AM Candle after it closes (9:00 AM NY onward)
        if self.state == "WAIT_8AM" and h1_bar:
            ny_h1_time = get_ny_time(h1_bar.time)
            ny_cur = get_ny_time(current_time)
            if ny_h1_time.hour == 8 and ny_cur.hour >= 9:
                self.candle_8am_high = h1_bar.high
                self.candle_8am_low = h1_bar.low
                self.candle_8am_mid = (h1_bar.high + h1_bar.low) / 2
                
                # Step 2: Find adjacent swing points
                h1_hist = history(self.symbol, TF.H1, 100)
                if h1_hist:
                    sw_highs = detect_swing_highs(h1_hist)
                    sw_lows = detect_swing_lows(h1_hist)
                    
                    # Find nearest above 8am high
                    above_highs = [s.price for s in sw_highs if s.price > self.candle_8am_high]
                    self.target_swing_high = min(above_highs) if above_highs else self.candle_8am_high + (self.candle_8am_high - self.candle_8am_low)
                    
                    # Find nearest below 8am low
                    below_lows = [s.price for s in sw_lows if s.price < self.candle_8am_low]
                    self.target_swing_low = max(below_lows) if below_lows else self.candle_8am_low - (self.candle_8am_high - self.candle_8am_low)
                
                self.state = "WAIT_SWEEP"
                self.step_tracker.record(
                    "Mark 8AM Boundary", 1, current_time, self.candle_8am_high, "H1",
                    f"8AM High: {self.candle_8am_high:.5f}, 8AM Low: {self.candle_8am_low:.5f}"
                )
                return []

        # Step 3: Wait for Sweep on M1
        if self.state == "WAIT_SWEEP":
            # Check if sweeping high (both 8am and adjacent swing)
            if m1_bar.high > self.target_swing_high and m1_bar.high > self.candle_8am_high:
                self.sweep_direction = "high"
                self.sweep_extreme = m1_bar.high
                self.state = "WAIT_MSS"
                self.step_tracker.record(
                    "Sweep Detected", 3, current_time, m1_bar.high, "M1",
                    f"Swept 8AM High and Swing High at {self.target_swing_high:.5f}"
                )
                
            # Check if sweeping low
            elif m1_bar.low < self.target_swing_low and m1_bar.low < self.candle_8am_low:
                self.sweep_direction = "low"
                self.sweep_extreme = m1_bar.low
                self.state = "WAIT_MSS"
                self.step_tracker.record(
                    "Sweep Detected", 3, current_time, m1_bar.low, "M1",
                    f"Swept 8AM Low and Swing Low at {self.target_swing_low:.5f}"
                )

        # Step 4: Wait for MSS (closing back inside boundary)
        elif self.state == "WAIT_MSS":
            m1_hist = history(self.symbol, TF.M1, 30)
            
            if self.sweep_direction == "high":
                self.sweep_extreme = max(self.sweep_extreme, m1_bar.high)
                # Check for bearish MSS + close back below 8AM High
                if m1_bar.close < self.candle_8am_high:
                    shifts = detect_mss(m1_hist, lookback=2)
                    bearish_mss = [s for s in shifts if s.direction == "bearish"]
                    
                    if bearish_mss:
                        # Setup valid!
                        self.state = "DONE"
                        self.step_tracker.record(
                            "Confirm MSS", 4, current_time, m1_bar.close, "M1",
                            "Bearish MSS formed and price closed back below 8AM high."
                        )
                        sl = self.sweep_extreme + (self.sweep_extreme * 0.0001)
                        tp = self.candle_8am_low # target opposite boundary
                        
                        return [Signal(self.id, Direction.SHORT, m1_bar.close, sl, tp, current_time, self.symbol)]
                        
            elif self.sweep_direction == "low":
                self.sweep_extreme = min(self.sweep_extreme, m1_bar.low)
                # Check for bullish MSS + close back above 8AM Low
                if m1_bar.close > self.candle_8am_low:
                    shifts = detect_mss(m1_hist, lookback=2)
                    bullish_mss = [s for s in shifts if s.direction == "bullish"]
                    
                    if bullish_mss:
                        # Setup valid!
                        self.state = "DONE"
                        self.step_tracker.record(
                            "Confirm MSS", 4, current_time, m1_bar.close, "M1",
                            "Bullish MSS formed and price closed back above 8AM low."
                        )
                        sl = self.sweep_extreme - (self.sweep_extreme * 0.0001)
                        tp = self.candle_8am_high
                        
                        return [Signal(self.id, Direction.LONG, m1_bar.close, sl, tp, current_time, self.symbol)]

        return []

    def on_position_update(self, bars, history, position, broker, step_tracker, current_time):
        """Move to BE when hitting 50% midpoint of 8AM candle."""
        if position.break_even_applied:
            return
            
        m1_bar = bars.get(TF.M1)
        if not m1_bar: return
        
        trade = position.trade
        if trade.direction == Direction.SHORT and m1_bar.low <= self.candle_8am_mid:
            broker.move_to_breakeven(self.id, m1_bar, step_tracker)
        elif trade.direction == Direction.LONG and m1_bar.high >= self.candle_8am_mid:
            broker.move_to_breakeven(self.id, m1_bar, step_tracker)
