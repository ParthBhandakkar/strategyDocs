"""
Strategy 19: Become a Profitable Trader in ONE DAY
Source: Faiz SMC
"""

from __future__ import annotations
from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.structure import is_bullish_orderflow, is_bearish_orderflow
from .base import BaseStrategy


class ProfitableOneDay(BaseStrategy):
    id = "s019_profitable_one_day"
    name = "Profitable in One Day"
    source_video = ""
    description = "High-conviction setups focusing on killzone trading with clear institutional order flow."
    timeframes = [TF.H1, TF.M15, TF.M1]
    
    playbook = [
        PlaybookStep(1, "Killzone Only", "Only trade during London or NY killzone.", "H1"),
        PlaybookStep(2, "Clear Bias", "Require clear H1 orderflow direction.", "H1"),
        PlaybookStep(3, "Key Level", "Price must be near H1 swing point.", "H1"),
        PlaybookStep(4, "M1 Trigger", "Execute on M1 MSS with tight SL.", "M1")
    ]

    def on_start(self):
        self.state = "WAIT_KILLZONE"
        self.bias = None

    def on_bar(self, bars, history, multi_symbol_bars, current_time) -> list[Signal]:
        return []