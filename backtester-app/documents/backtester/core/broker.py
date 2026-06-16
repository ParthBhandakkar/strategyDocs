"""
Simulated Broker — handles order execution, fill simulation, SL/TP management.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from . import Bar, Signal, Trade, Position, Direction, OrderType, TradeStatus
from .events import FillEvent, OrderEvent
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
        self.pip_value_per_lot = 10.0
        self._next_trade_id = 1
        self.open_positions: list[Position] = []
        self.closed_trades: list[Trade] = []

    def set_pip_value(self, symbol: str):
        """Set pip/point size and USD value per standard lot."""
        sym = symbol.upper()
        if "JPY" in sym:
            self.pip_value = 0.01
            self.pip_value_per_lot = 10.0
        elif "XAU" in sym or "GOLD" in sym:
            self.pip_value = 0.1
            self.pip_value_per_lot = 10.0
        elif "XAG" in sym or "SILVER" in sym:
            self.pip_value = 0.01
            self.pip_value_per_lot = 50.0
        elif "BTC" in sym:
            self.pip_value = 1.0
            self.pip_value_per_lot = 1.0
        elif "ETH" in sym:
            self.pip_value = 0.1
            self.pip_value_per_lot = 1.0
        else:
            self.pip_value = 0.0001
            self.pip_value_per_lot = 10.0

    def execute_signal(
        self,
        signal: Signal,
        current_bar: Bar,
        balance: float,
        risk_per_trade: float = 0.01,
    ) -> Optional[FillEvent]:
        """
        Execute a trading signal. Returns a FillEvent if the order is filled.
        """
        # Calculate lot size based on risk
        risk_amount = balance * risk_per_trade
        sl_distance = abs(signal.entry_price - signal.stop_loss)
        if sl_distance <= 0:
            return None

        # Pip value per lot (standard lot = 100,000 units for forex)
        pip_distance = sl_distance / self.pip_value
        if pip_distance <= 0:
            return None

        # Approximate: 1 standard lot on EURUSD = $10/pip
        lot_size = risk_amount / (pip_distance * self.pip_value_per_lot)
        lot_size = max(0.01, round(lot_size, 2))  # Min 0.01 lot

        # Apply spread and slippage
        spread = self.spread_pips * self.pip_value
        slippage = self.slippage_pips * self.pip_value

        if signal.direction == Direction.LONG:
            fill_price = signal.entry_price + spread / 2 + slippage
        else:
            fill_price = signal.entry_price - spread / 2 - slippage

        commission = self.commission_per_lot * lot_size

        # Create the trade
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
            metadata=signal.metadata.copy(),
        )
        self._next_trade_id += 1

        # Create position
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

    def update_positions(self, bar: Bar, step_tracker: StepTracker | None = None) -> list[Trade]:
        """
        Check all open positions against the current bar for SL/TP hits.
        Returns list of newly closed trades.
        """
        closed = []
        remaining = []

        for pos in self.open_positions:
            trade = pos.trade
            closed_trade = None

            # Check SL hit first (worst case first)
            if pos.is_sl_hit(bar):
                exit_price = pos.current_sl
                trade.close(bar.time, exit_price, self.pip_value)
                self._apply_usd_pnl(trade, pos.lot_size)
                closed_trade = trade

                if step_tracker:
                    step_tracker.add_step_to_trade(
                        trade.id,
                        "Stop Loss Hit",
                        99,
                        bar.time,
                        exit_price,
                        "",
                        f"Stop loss triggered at {exit_price:.5f}",
                    )

            # Check TP hit
            elif pos.is_tp_hit(bar):
                exit_price = pos.current_tp
                trade.close(bar.time, exit_price, self.pip_value)
                self._apply_usd_pnl(trade, pos.lot_size)
                closed_trade = trade

                if step_tracker:
                    step_tracker.add_step_to_trade(
                        trade.id,
                        "Take Profit Hit",
                        100,
                        bar.time,
                        exit_price,
                        "",
                        f"Take profit reached at {exit_price:.5f}",
                    )

            if closed_trade:
                # Attach steps from step tracker
                if step_tracker:
                    closed_trade.steps = step_tracker.get_trade_steps(closed_trade.id)
                self.closed_trades.append(closed_trade)
                closed.append(closed_trade)
            else:
                remaining.append(pos)

        self.open_positions = remaining
        return closed

    def _apply_usd_pnl(self, trade: Trade, lot_size: float):
        """Store consistent USD PnL on the trade metadata."""
        pnl_usd = trade.pnl_pips * self.pip_value_per_lot * lot_size
        commission = self.commission_per_lot * lot_size
        pnl_usd -= commission
        trade.pnl = pnl_usd
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)
        trade.metadata["lot_size"] = lot_size

    def has_open_position(self, strategy_id: str | None = None) -> bool:
        """Check if there's an open position (optionally for a specific strategy)."""
        if strategy_id:
            return any(p.trade.strategy_id == strategy_id for p in self.open_positions)
        return len(self.open_positions) > 0

    def get_open_position(self, strategy_id: str) -> Optional[Position]:
        """Get the open position for a strategy."""
        for p in self.open_positions:
            if p.trade.strategy_id == strategy_id:
                return p
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
