"""
Strategy 16: The Easiest Trading Strategy for Beginners
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.structure import is_bullish_orderflow, is_bearish_orderflow
from .base import BaseStrategy


class OneCandleBeginners(BaseStrategy):
    id = "s016_one_candle_beginners"
    name = "One Candle Strategy (Beginners)"
    source_video = ""
    description = "Simplified single-candle setup for beginners. Trade in trend direction after pullback candle."
    timeframes = [TF.H1, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Trend Identification", "Check H1 for clear trend direction.", "H1"),
        PlaybookStep(2, "Pullback Candle", "Wait for a pullback candle that respects trend.", "M15"),
        PlaybookStep(3, "Entry Trigger", "Enter on next bullish/bearish candle close.", "M1"),
        PlaybookStep(4, "SL Placement", "SL below/above pullback candle wick.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_BIAS"
        self.bias = None

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []