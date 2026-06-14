"""
Step Tracker — records strategy step executions for the Trade Inspector.
Each strategy logs its steps (e.g., "Identified bearish orderflow", "Sweep detected")
and these get attached to the resulting Trade for display in the dashboard.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any

from . import StepRecord


class StepTracker:
    """
    Accumulates strategy step records during bar processing.
    Steps are later attached to the Trade that results from them.
    """

    def __init__(self, strategy_id: str):
        self.strategy_id = strategy_id
        self._pending_steps: list[StepRecord] = []
        self._trade_steps: dict[int, list[StepRecord]] = {}  # trade_id -> steps

    def record(
        self,
        step_name: str,
        step_number: int,
        timestamp: datetime,
        price_level: float,
        timeframe: str,
        description: str,
        metadata: dict[str, Any] | None = None,
    ):
        """Record a strategy step. Steps are pending until assigned to a trade."""
        step = StepRecord(
            step_name=step_name,
            step_number=step_number,
            timestamp=timestamp,
            price_level=price_level,
            timeframe=timeframe,
            description=description,
            metadata=metadata or {},
        )
        self._pending_steps.append(step)

    def assign_to_trade(self, trade_id: int):
        """
        Assign all pending steps to a specific trade.
        Called when a signal results in an actual trade entry.
        """
        if trade_id not in self._trade_steps:
            self._trade_steps[trade_id] = []
        self._trade_steps[trade_id].extend(self._pending_steps)
        self._pending_steps = []

    def add_step_to_trade(
        self,
        trade_id: int,
        step_name: str,
        step_number: int,
        timestamp: datetime,
        price_level: float,
        timeframe: str,
        description: str,
        metadata: dict[str, Any] | None = None,
    ):
        """Add a step directly to an existing trade (e.g., SL moved to BE)."""
        step = StepRecord(
            step_name=step_name,
            step_number=step_number,
            timestamp=timestamp,
            price_level=price_level,
            timeframe=timeframe,
            description=description,
            metadata=metadata or {},
        )
        if trade_id not in self._trade_steps:
            self._trade_steps[trade_id] = []
        self._trade_steps[trade_id].append(step)

    def get_trade_steps(self, trade_id: int) -> list[StepRecord]:
        """Get all steps associated with a trade."""
        return self._trade_steps.get(trade_id, [])

    def clear_pending(self):
        """Discard pending steps (e.g., setup invalidated, no trade taken)."""
        self._pending_steps = []

    def has_pending(self) -> bool:
        """Check if there are pending steps not yet assigned to a trade."""
        return len(self._pending_steps) > 0
