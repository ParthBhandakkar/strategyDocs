"""
Base Strategy class that all strategies must inherit from.
Defines metadata, lifecycle methods, and playbook structure.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable, Optional

from backtester.core import Bar, Signal, Position, PlaybookStep
from backtester.core.timeframes import TF
from backtester.core.step_tracker import StepTracker
from backtester.core.broker import SimulatedBroker


class BaseStrategy(ABC):
    """
    Abstract base class for all backtester strategies.
    Provides standard hooks for market events and position management.
    """

    id: str = "base_strategy"
    name: str = "Base Strategy"
    source_video: str = ""
    description: str = ""
    timeframes: list[TF] = []
    playbook: list[PlaybookStep] = []
    
    # Optional list of extra symbols to fetch (for SMT divergence)
    extra_symbols: list[str] = []

    def __init__(self):
        self.symbol: str = ""
        self.broker: Optional[SimulatedBroker] = None
        self.step_tracker: Optional[StepTracker] = None

    def initialize(self, symbol: str, broker: SimulatedBroker, step_tracker: StepTracker):
        """Called once before the backtest begins."""
        self.symbol = symbol
        self.broker = broker
        self.step_tracker = step_tracker
        self.on_start()

    def on_start(self):
        """Hook for subclass initialization logic (e.g., state variables)."""
        pass

    @abstractmethod
    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        """
        Main logic loop. Called when a new bar arrives on ANY subscribed timeframe.
        
        Args:
            bars: dict mapping TF to the latest completed Bar for the primary symbol.
            history: function to retrieve past bars `history(symbol, TF, lookback)`
            multi_symbol_bars: dict mapping symbol to a dict of TF -> Bar.
            current_time: The engine's current time.
            
        Returns:
            List of Signals to execute.
        """
        pass

    def on_position_update(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        position: Position,
        broker: SimulatedBroker,
        step_tracker: StepTracker,
        current_time: datetime,
    ):
        """
        Called on every bar IF there is an open position for this strategy.
        Used for trailing stops, break-even rules, or early exits.
        """
        pass
