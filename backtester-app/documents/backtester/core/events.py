"""
Event types for the event-driven backtesting engine.
Each event flows through the engine's event queue.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .timeframes import TF
from . import Bar, Signal, Direction, OrderType


class EventType:
    MARKET = "MARKET"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"
    STEP = "STEP"


@dataclass
class Event:
    """Base event class."""
    timestamp: datetime
    type: str = ""


@dataclass
class MarketEvent(Event):
    """Emitted when new bar(s) arrive for one or more timeframes."""
    type: str = EventType.MARKET
    # Maps TF -> latest completed bar for each subscribed timeframe
    bars: dict[TF, Bar] = field(default_factory=dict)
    # For multi-symbol: maps symbol -> {TF -> Bar}
    multi_symbol_bars: dict[str, dict[TF, Bar]] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp and self.bars:
            # Use the timestamp from the first available bar
            for bar in self.bars.values():
                self.timestamp = bar.time
                break


@dataclass
class SignalEvent(Event):
    """Emitted when a strategy generates a trade signal."""
    type: str = EventType.SIGNAL
    signal: Signal = None


@dataclass
class OrderEvent(Event):
    """Emitted when an order is placed with the broker."""
    type: str = EventType.ORDER
    strategy_id: str = ""
    symbol: str = ""
    direction: Direction = Direction.LONG
    order_type: OrderType = OrderType.MARKET
    price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    lot_size: float = 0.01
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FillEvent(Event):
    """Emitted when an order is filled by the broker."""
    type: str = EventType.FILL
    strategy_id: str = ""
    symbol: str = ""
    direction: Direction = Direction.LONG
    fill_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    lot_size: float = 0.01
    commission: float = 0.0
    slippage: float = 0.0
    trade_id: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepEvent(Event):
    """Emitted when a strategy step is triggered — for audit trail."""
    type: str = EventType.STEP
    strategy_id: str = ""
    trade_id: int = -1  # -1 means not yet associated with a trade
    step_name: str = ""
    step_number: int = 0
    price_level: float = 0.0
    timeframe: str = ""
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
