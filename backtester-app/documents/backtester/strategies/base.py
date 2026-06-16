"""
Base strategy contract for folder-based strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable, Optional

from backtester.core import Bar, Signal, PlaybookStep
from backtester.core.timeframes import TF


class BaseStrategy(ABC):
    id: str = ""
    name: str = ""
    source_video: str = ""
    description: str = ""
    timeframes: list[TF] = []
    extra_symbols: list[str] = []
    playbook: list[PlaybookStep] = []

    def __init__(self) -> None:
        self.symbol = ""
        self.broker: Any = None
        self.step_tracker: Any = None

    def initialize(self, symbol: str, broker: Any, step_tracker: Any) -> None:
        self.symbol = symbol
        self.broker = broker
        self.step_tracker = step_tracker

    @abstractmethod
    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[..., list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        raise NotImplementedError

    def on_position_update(
        self,
        bars: dict[TF, Bar],
        history: Callable[..., list[Bar]],
        position: Any,
        broker: Any,
        step_tracker: Any,
        current_time: datetime,
    ) -> None:
        return None

    def required_timeframes(self) -> list[TF]:
        return list(self.timeframes)
