"""
Strategy 13: The 8:00 AM Candle Strategy
Source: Faiz SMC ("The 800 AM Candle Strategy")
Video URL: https://www.youtube.com/watch?v=2cuaTYjEw9Q

BIAS FIX (2026-06-19):
  Original bias: Same as s012 — captured 8 AM H1 high/low at hour open instead of after
  the 8-9 AM candle closed.
  Fix: Wait until 9:00 AM NY; use the completed 8 AM H1 bar from history.

BACKTEST RESULTS (local Exness CSV, 2024-01-01 to 2024-06-30, all pairs):
  AUDCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  AUDUSD: Trades: 58 | Win rate: 3.45% | PF: 0.2 | PnL: $-0.02 | Max DD: 19.74% | Avg R:R: -0.33
  BTCUSD: Trades: 118 | Win rate: 6.78% | PF: 0.34 | PnL: $-8220.52 | Max DD: 16.35% | Avg R:R: -0.13
  CADCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  CADJPY: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  CHFJPY: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  ETHUSD: Trades: 109 | Win rate: 5.5% | PF: 0.16 | PnL: $-686.44 | Max DD: 21.63% | Avg R:R: -0.18
  EURCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  EURGBP: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  EURUSD: Trades: 55 | Win rate: 9.09% | PF: 0.49 | PnL: $-0.01 | Max DD: 9.32% | Avg R:R: -0.14
  GBPAUD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPCAD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPJPY: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPNZD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPUSD: Trades: 56 | Win rate: 7.14% | PF: 0.44 | PnL: $-0.01 | Max DD: 11.92% | Avg R:R: -0.21
  NZDJPY: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  NZDUSD: Trades: 58 | Win rate: 8.62% | PF: 0.49 | PnL: $-0.01 | Max DD: 9.86% | Avg R:R: -0.08
  USDCAD: Trades: 48 | Win rate: 10.42% | PF: 0.41 | PnL: $-0.02 | Max DD: 11.45% | Avg R:R: -0.18
  USDCHF: Trades: 60 | Win rate: 8.33% | PF: 0.31 | PnL: $-0.01 | Max DD: 13.09% | Avg R:R: -0.22
  USDJPY: Trades: 71 | Win rate: 4.23% | PF: 0.27 | PnL: $-2.70 | Max DD: 20.83% | Avg R:R: -0.29
  XAGUSD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  XAUUSD: Trades: 67 | Win rate: 13.43% | PF: 0.69 | PnL: $-45.52 | Max DD: 13.46% | Avg R:R: -0.13
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.structure import detect_swing_highs, detect_swing_lows, detect_mss
from .base import BaseStrategy


class The800AMCandleStrategy(BaseStrategy):
    id = "s013_800am_candle"
    name = "The 8:00 AM Candle Strategy"
    source_video = "https://www.youtube.com/watch?v=2cuaTYjEw9Q"
    description = "Uses the 8:00 AM hourly candle as a liquidity pool. Waits for price to sweep the 8AM H/L plus adjacent swing, then enter on MSS."
    timeframes = [TF.H1, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Mark 8AM Range", "Wait for 8:00 AM candle to close. Mark high and low.", "H1"),
        PlaybookStep(2, "Find Adjacent Swing", "Locate nearest H1 swing point beyond 8AM boundary.", "H1"),
        PlaybookStep(3, "Wait for Dual Sweep", "Watch M1 for sweep of BOTH 8AM boundary and swing point.", "M1"),
        PlaybookStep(4, "MSS Entry", "Enter when price closes back inside 8AM range with MSS.", "M1"),
        PlaybookStep(5, "Risk Management", "SL beyond sweep wick. Target 50% midpoint for partial.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_8AM"
        self.am8_high = 0.0
        self.am8_low = 0.0
        self.am8_mid = 0.0
        self.swing_high = 0.0
        self.swing_low = 0.0
        self.sweep_dir = None
        self.sweep_extreme = 0.0
        self.trade_date = None

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        h1_bar = bars.get(TF.H1)
        m1_bar = bars.get(TF.M1)
        if not m1_bar:
            return []

        ny_time = get_ny_time(current_time)
        
        if self.trade_date != ny_time.date() and ny_time.hour == 0:
            self.on_start()
            self.trade_date = ny_time.date()

        # Capture 8AM candle after it closes (9:00 AM NY onward)
        if self.state == "WAIT_8AM" and h1_bar:
            ny_h1 = get_ny_time(h1_bar.time)
            ny_cur = get_ny_time(current_time)
            if ny_h1.hour == 8 and ny_cur.hour >= 9:
                self.am8_high = h1_bar.high
                self.am8_low = h1_bar.low
                self.am8_mid = (h1_bar.high + h1_bar.low) / 2
                
                h1_hist = history(self.symbol, TF.H1, 100)
                if h1_hist:
                    sw_highs = detect_swing_highs(h1_hist)
                    sw_lows = detect_swing_lows(h1_hist)
                    
                    above = [s.price for s in sw_highs if s.price > self.am8_high]
                    self.swing_high = min(above) if above else self.am8_high + (self.am8_high - self.am8_low)
                    
                    below = [s.price for s in sw_lows if s.price < self.am8_low]
                    self.swing_low = max(below) if below else self.am8_low - (self.am8_high - self.am8_low)
                
                self.state = "WAIT_SWEEP"
                self.step_tracker.record("8AM Marked", 1, current_time, self.am8_high, "H1",
                    f"8AM H: {self.am8_high:.5f}, L: {self.am8_low:.5f}")
                return []

        if self.state == "WAIT_SWEEP":
            # Check dual sweep (8AM + swing)
            if m1_bar.high > self.swing_high and m1_bar.high > self.am8_high:
                self.sweep_dir = "high"
                self.sweep_extreme = m1_bar.high
                self.state = "WAIT_MSS"
                
            elif m1_bar.low < self.swing_low and m1_bar.low < self.am8_low:
                self.sweep_dir = "low"
                self.sweep_extreme = m1_bar.low
                self.state = "WAIT_MSS"

        elif self.state == "WAIT_MSS":
            if self.sweep_dir == "high":
                self.sweep_extreme = max(self.sweep_extreme, m1_bar.high)
                if m1_bar.close < self.am8_high:
                    m1_hist = history(self.symbol, TF.M1, 20)
                    shifts = detect_mss(m1_hist, lookback=2)
                    bearish = [s for s in shifts if s.direction == "bearish"]
                    
                    if bearish:
                        self.state = "DONE"
                        sl = self.sweep_extreme + (self.sweep_extreme * 0.0001)
                        tp = self.am8_low
                        self.step_tracker.record("Short Entry", 4, current_time, m1_bar.close, "M1", "Bearish MSS")
                        return [Signal(self.id, Direction.SHORT, m1_bar.close, sl, tp, current_time, self.symbol)]
                        
            elif self.sweep_dir == "low":
                self.sweep_extreme = min(self.sweep_extreme, m1_bar.low)
                if m1_bar.close > self.am8_low:
                    m1_hist = history(self.symbol, TF.M1, 20)
                    shifts = detect_mss(m1_hist, lookback=2)
                    bullish = [s for s in shifts if s.direction == "bullish"]
                    
                    if bullish:
                        self.state = "DONE"
                        sl = self.sweep_extreme - (self.sweep_extreme * 0.0001)
                        tp = self.am8_high
                        self.step_tracker.record("Long Entry", 4, current_time, m1_bar.close, "M1", "Bullish MSS")
                        return [Signal(self.id, Direction.LONG, m1_bar.close, sl, tp, current_time, self.symbol)]

        return []

    def on_position_update(self, bars, history, position, broker, step_tracker, current_time):
        if position.break_even_applied:
            return
        m1_bar = bars.get(TF.M1)
        if not m1_bar:
            return
        trade = position.trade
        if trade.direction == Direction.SHORT and m1_bar.low <= self.am8_mid:
            broker.move_to_breakeven(self.id, m1_bar, step_tracker)
        elif trade.direction == Direction.LONG and m1_bar.high >= self.am8_mid:
            broker.move_to_breakeven(self.id, m1_bar, step_tracker)