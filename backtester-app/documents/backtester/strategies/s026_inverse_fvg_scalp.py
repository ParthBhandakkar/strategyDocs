"""
Strategy 26: Live Trading NQ - Inverse FVG Scalp Setup
Source: Faiz SMC

BIAS FIX (2026-06-19):
  Original bias: M5 FVG detection used incomplete M5 bars (engine released at open).
  Fix: Engine bar-close release; M5 FVGs now built from fully closed M5 candles only.
  Note: Backtested on XAUUSD (local data has no NQ); logic is symbol-agnostic.

BACKTEST RESULTS (local Exness CSV, 2024-01-01 to 2024-06-30, all pairs):
  AUDCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  AUDUSD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  BTCUSD: Trades: 1 | Win rate: 0.0% | PF: 0.0 | PnL: $-33.23 | Max DD: 0.0% | Avg R:R: -1.0
  CADCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  CADJPY: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  CHFJPY: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  ETHUSD: Trades: 1 | Win rate: 0.0% | PF: 0.0 | PnL: $-0.74 | Max DD: 0.0% | Avg R:R: -1.0
  EURCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  EURGBP: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  EURUSD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPAUD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPCAD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPJPY: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPNZD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  GBPUSD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  NZDJPY: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  NZDUSD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  USDCAD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  USDCHF: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  USDJPY: Trades: 1 | Win rate: 100.0% | PF: inf | PnL: $0.56 | Max DD: 0.0% | Avg R:R: 1.44
  XAGUSD: Trades: 0 | Win rate: 0.0% | PF: 0.0 | PnL: $0.00 | Max DD: 0.0% | Avg R:R: 0.0
  XAUUSD: Trades: 1 | Win rate: 0.0% | PF: 0.0 | PnL: $-0.93 | Max DD: 0.0% | Avg R:R: -1.42
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