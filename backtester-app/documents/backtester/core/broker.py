"""
Simulated Broker — handles order execution, fill simulation, SL/TP management.
"""

from __future__ import annotations

from typing import Optional

from . import Bar, Signal, Trade, Position, Direction, OrderType, TradeStatus
from .events import FillEvent
from .step_tracker import StepTracker


class SimulatedBroker:
    """
    Simulates order execution with configurable spread, slippage, and commission.
    Manages open positions and checks SL/TP hits each bar.
    """

    def __init__(
        self,
        spread_pips: float = 1.0,
        slippage_pips: float = 0.5,
        commission_per_lot: float = 7.0,
        pip_value: float = 0.0001,
    ):
        self.spread_pips = spread_pips
        self.slippage_pips = slippage_pips
        self.commission_per_lot = commission_per_lot
        self.pip_value = pip_value
        self._symbol = "EURUSD"
        self._next_trade_id = 1
        self.open_positions: list[Position] = []
        self.closed_trades: list[Trade] = []

    def set_pip_value(self, symbol: str):
        """Set pip value based on symbol type."""
        self._symbol = symbol.upper()
        sym = self._symbol
        if "JPY" in sym:
            self.pip_value = 0.01
        elif "XAU" in sym or "GOLD" in sym:
            self.pip_value = 0.1
        elif "XAG" in sym or "SILVER" in sym:
            self.pip_value = 0.01
        elif "BTC" in sym:
            self.pip_value = 1.0
        elif "ETH" in sym:
            self.pip_value = 0.1
        else:
            self.pip_value = 0.0001

    def pip_value_usd_per_lot(self, price: float) -> float:
        """USD value of one pip for one standard lot."""
        sym = self._symbol
        if "XAU" in sym:
            return 10.0
        if "XAG" in sym:
            return 50.0
        if "BTC" in sym:
            return 1.0
        if "ETH" in sym:
            return 0.1
        if "JPY" in sym and price > 0:
            return 1000.0 / price
        return 10.0

    def execute_signal(
        self,
        signal: Signal,
        current_bar: Bar,
        balance: float,
        risk_per_trade: float = 0.01,
    ) -> Optional[FillEvent]:
        """Execute a trading signal. Returns a FillEvent if the order is filled."""
        risk_amount = balance * risk_per_trade
        sl_distance = abs(signal.entry_price - signal.stop_loss)
        if sl_distance <= 0:
            return None

        pip_distance = sl_distance / self.pip_value
        if pip_distance <= 0:
            return None

        pip_val_usd = self.pip_value_usd_per_lot(signal.entry_price)
        lot_size = risk_amount / (pip_distance * pip_val_usd)
        lot_size = max(0.01, round(lot_size, 2))

        spread = self.spread_pips * self.pip_value
        slippage = self.slippage_pips * self.pip_value

        if signal.direction.value == "LONG":
            fill_price = signal.entry_price + spread / 2 + slippage
        else:
            fill_price = signal.entry_price - spread / 2 - slippage

        commission = self.commission_per_lot * lot_size

        trade = Trade(
            id=self._next_trade_id,
            strategy_id=signal.strategy_id,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_time=signal.timestamp,
            entry_price=fill_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            status=TradeStatus.OPEN,
            metadata={
                **signal.metadata.copy(),
                "commission": commission,
                "lot_size": lot_size,
            },
        )
        self._next_trade_id += 1

        position = Position(trade=trade, lot_size=lot_size)
        self.open_positions.append(position)

        return FillEvent(
            timestamp=signal.timestamp,
            strategy_id=signal.strategy_id,
            symbol=signal.symbol,
            direction=signal.direction,
            fill_price=fill_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            lot_size=lot_size,
            commission=commission,
            slippage=slippage,
            trade_id=trade.id,
            metadata=signal.metadata.copy(),
        )

    def _close_position(
        self,
        pos: Position,
        bar: Bar,
        exit_price: float,
        step_tracker: StepTracker | None,
        step_name: str,
        step_number: int,
        description: str,
    ) -> Trade:
        trade = pos.trade
        trade.close(
            bar.time,
            exit_price,
            self.pip_value,
            lot_size=pos.lot_size,
            pip_value_usd_per_lot=self.pip_value_usd_per_lot(exit_price),
        )
        if step_tracker:
            step_tracker.add_step_to_trade(
                trade.id,
                step_name,
                step_number,
                bar.time,
                exit_price,
                "",
                description,
            )
            trade.steps = step_tracker.get_trade_steps(trade.id)
        self.closed_trades.append(trade)
        return trade

    def update_positions(self, bar: Bar, step_tracker: StepTracker | None = None) -> list[Trade]:
        """Check all open positions against the current bar for SL/TP hits."""
        closed = []
        remaining = []

        for pos in self.open_positions:
            if pos.is_sl_hit(bar):
                closed.append(
                    self._close_position(
                        pos,
                        bar,
                        pos.current_sl,
                        step_tracker,
                        "Stop Loss Hit",
                        99,
                        f"Stop loss triggered at {pos.current_sl:.5f}",
                    )
                )
            elif pos.is_tp_hit(bar):
                closed.append(
                    self._close_position(
                        pos,
                        bar,
                        pos.current_tp,
                        step_tracker,
                        "Take Profit Hit",
                        100,
                        f"Take profit reached at {pos.current_tp:.5f}",
                    )
                )
            else:
                remaining.append(pos)

        self.open_positions = remaining
        return closed

    def has_open_position(self, strategy_id: str | None = None) -> bool:
        """Check if there's an open position (optionally for a specific strategy)."""
        if strategy_id:
            return any(p.trade.strategy_id == strategy_id for p in self.open_positions)
        return len(self.open_positions) > 0

    def get_open_position(self, strategy_id: str) -> Optional[Position]:
        """Get the open position for a strategy."""
        for pos in self.open_positions:
            if pos.trade.strategy_id == strategy_id:
                return pos
        return None

    def move_to_breakeven(self, strategy_id: str, bar: Bar, step_tracker: StepTracker | None = None):
        """Move stop loss to breakeven for a strategy's open position."""
        pos = self.get_open_position(strategy_id)
        if pos and not pos.break_even_applied:
            pos.move_sl_to_breakeven()
            if step_tracker:
                step_tracker.add_step_to_trade(
                    pos.trade.id,
                    "Stop Loss to Breakeven",
                    50,
                    bar.time,
                    pos.trade.entry_price,
                    "",
                    f"SL moved to breakeven at {pos.trade.entry_price:.5f}",
                )
