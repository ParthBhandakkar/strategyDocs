"""
Strategy 01: Orderflow & Volume Profile
Source: ICT/SMC Concepts
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.structure import detect_swing_highs, detect_swing_lows, is_bullish_orderflow, is_bearish_orderflow
from backtester.indicators.fvg import detect_fvg, get_unmitigated_fvgs
from .base import BaseStrategy


class OrderflowVolumeProfile(BaseStrategy):
    id = "s001_orderflow_volume_profile"
    name = "Orderflow & Volume Profile"
    source_video = ""
    description = "Uses H1 orderflow to determine bias, then maps liquidity zones on H4 for draw-on-liquidity targets."
    timeframes = [TF.H4, TF.H1]
    
    playbook = [
        PlaybookStep(1, "H1 Orderflow", "Determine dominant orderflow direction on H1. Must respect FVGs.", "H1"),
        PlaybookStep(2, "H4 Liquidity Zones", "Map major H4 structural pools (swing highs/lows, equal highs/lows).", "H4"),
        PlaybookStep(3, "Execution Window", "Trade during active New York sessions.", "H1"),
        PlaybookStep(4, "M15 Entry Setup", "Wait for price to sweep liquidity and form MSS/CISD on M15.", "M15")
    ]

    def on_start(self):
        self.state = "WAIT_H1_BIAS"
        self.bias = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        h1_bar = bars.get(TF.H1)
        h4_bar = bars.get(TF.H4)
        if not h1_bar:
            return []

        # Step 1: Determine H1 Orderflow Bias
        if self.state == "WAIT_H1_BIAS":
            h1_hist = history(self.symbol, TF.H1, 30)
            if h1_hist:
                if is_bullish_orderflow(h1_hist):
                    self.bias = "bullish"
                    self.state = "MONITOR_LIQUIDITY"
                elif is_bearish_orderflow(h1_hist):
                    self.bias = "bearish"
                    self.state = "MONITOR_LIQUIDITY"

        # Step 2: Map Liquidity Zones on H4
        if self.state == "MONITOR_LIQUIDITY" and h4_bar:
            h4_hist = history(self.symbol, TF.H4, 50)
            if h4_hist:
                sw_highs = detect_swing_highs(h4_hist, lookback=3)
                sw_lows = detect_swing_lows(h4_hist, lookback=3)
                
                if self.bias == "bearish" and sw_lows:
                    # Look for liquidity sweeps below
                    recent_low = min([s.price for s in sw_lows[-3:]])
                    if h4_bar.low <= recent_low:
                        self.step_tracker.record(
                            "Liquidity Sweep", 2, current_time, h4_bar.low, "H4",
                            f"H4 liquidity sweep at {recent_low:.5f}"
                        )
                
                elif self.bias == "bullish" and sw_highs:
                    recent_high = max([s.price for s in sw_highs[-3:]])
                    if h4_bar.high >= recent_high:
                        self.step_tracker.record(
                            "Liquidity Sweep", 2, current_time, h4_bar.high, "H4",
                            f"H4 liquidity sweep at {recent_high:.5f}"
                        )

        return []