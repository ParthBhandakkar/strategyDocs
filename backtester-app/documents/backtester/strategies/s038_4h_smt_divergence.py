"""
Strategy 38: 4H Core Trend & SMT Divergence System
Source: Faiz SMC ("Ultimate ICT Gold Trading Strategy With 73% Winrate..")
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import is_in_killzone, is_restricted_hour
from backtester.indicators.fvg import detect_fvg, get_unmitigated_fvgs
from backtester.indicators.smt import detect_smt_divergence
from .base import BaseStrategy


class CoreTrendSMTDivergence(BaseStrategy):
    id = "s038_4h_smt_divergence"
    name = "4H SMT Divergence (Gold/Silver)"
    source_video = "https://www.youtube.com/watch?v=ugsA3FHiF0I"
    description = "Uses 4H FVGs and checks for SMT divergence between correlated assets (e.g., Gold vs Silver) on the 15M chart inside killzones to confirm entries."
    timeframes = [TF.H4, TF.M15]
    
    # Needs a correlated asset (e.g. XAGUSD for XAUUSD)
    extra_symbols = ["XAGUSD"]
    
    playbook = [
        PlaybookStep(1, "4H Trend & Arrays", "Identify bullish/bearish orderflow and mark nearest unmitigated 4H FVGs.", "H4"),
        PlaybookStep(2, "Monitor FVG (15M)", "Wait for price to drop into the 4H FVG on the 15-Minute chart.", "M15"),
        PlaybookStep(3, "SMT Divergence", "Compare with correlated asset. Look for one sweeping a low while the other holds a higher low.", "M15"),
        PlaybookStep(4, "CISD Execution", "Wait for 15M candle to close past the manipulation sequence (CISD). Enter on retest or close.", "M15"),
        PlaybookStep(5, "Risk Rules", "Execute only in London/NY killzones. Avoid Lunch hour.", "M15")
    ]

    def on_start(self):
        self.state = "MONITOR"
        self.h4_fvgs = []
        # If the main symbol isn't XAUUSD/Gold, this strategy might not make sense unless configured properly,
        # but we'll run it against the primary symbol and the first extra_symbol.
        self.correlated_symbol = self.extra_symbols[0]

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        h4_bar = bars.get(TF.H4)
        m15_bar = bars.get(TF.M15)
        if not m15_bar: return []

        # Step 5: Killzone check
        if is_restricted_hour(current_time):
            return []
        if not (is_in_killzone(current_time, "london_killzone") or is_in_killzone(current_time, "ny_killzone")):
            return []

        # Step 1: Detect 4H FVGs
        if h4_bar:
            h4_hist = history(self.symbol, TF.H4, 100)
            self.h4_fvgs = get_unmitigated_fvgs(detect_fvg(h4_hist, min_gap_pips=2.0))

        # Check if price is inside any 4H FVG
        active_fvg = None
        for fvg in self.h4_fvgs:
            if fvg.contains_price(m15_bar.close):
                active_fvg = fvg
                break

        if not active_fvg:
            return []

        # Step 3: SMT Divergence
        # We need the 15m history of both symbols
        primary_hist = history(self.symbol, TF.M15, 20)
        
        corr_bars = multi_symbol_bars.get(self.correlated_symbol, {})
        if not corr_bars:
            return []
            
        # To get the correlated history, we'd normally call history(self.correlated_symbol, TF.M15, 20)
        # Assuming the history callable supports this:
        secondary_hist = history(self.correlated_symbol, TF.M15, 20)

        divergences = detect_smt_divergence(primary_hist, secondary_hist)
        
        if divergences:
            div = divergences[-1]
            
            # Step 4: CISD Execution
            # Simplified: we use the SMT divergence directly if it aligns with the 4H FVG direction
            if div.direction == "bullish" and active_fvg.direction == "bullish":
                self.step_tracker.record(
                    "SMT Confirmed", 3, current_time, m15_bar.close, "M15",
                    f"Bullish SMT Divergence with {self.correlated_symbol} inside 4H FVG."
                )
                
                # Setup Long
                sl = div.primary_price - (div.primary_price * 0.0005)
                risk = m15_bar.close - sl
                tp = m15_bar.close + (risk * 2)
                
                return [Signal(self.id, Direction.LONG, m15_bar.close, sl, tp, current_time, self.symbol)]
                
            elif div.direction == "bearish" and active_fvg.direction == "bearish":
                self.step_tracker.record(
                    "SMT Confirmed", 3, current_time, m15_bar.close, "M15",
                    f"Bearish SMT Divergence with {self.correlated_symbol} inside 4H FVG."
                )
                
                # Setup Short
                sl = div.primary_price + (div.primary_price * 0.0005)
                risk = sl - m15_bar.close
                tp = m15_bar.close - (risk * 2)
                
                return [Signal(self.id, Direction.SHORT, m15_bar.close, sl, tp, current_time, self.symbol)]

        return []
