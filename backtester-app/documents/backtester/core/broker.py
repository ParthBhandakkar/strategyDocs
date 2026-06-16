"""
Simulated Broker — order execution with symbol-aware USD risk sizing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from . import Bar, Signal, Trade, Position, Direction, TradeStatus
from .events import FillEvent
from .step_tracker import StepTracker


class SimulatedBroker:
    """Simulates fills, commissions, and USD PnL."""

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
        sym = symbol.upper()
        if "JPY" in sym:
            self.pip_value = 0.01
            self.pip_value_per_lot = 6.5
        elif "XAU" in sym or "GOLD" in sym:
            self.pip_value = 0.1
            self.pip_value_per_lot = 10.0
        elif "XAG" in sym or "SILVER" in sym:
            self.pip_value = 0.01
            self.pip_value_per_lot = 5.0
        elif sym in {"BTCUSD", "ETHUSD"}:
            self.pip_value = 1.0
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
        risk_amount = balance * risk_per_trade
        sl_distance = abs(signal.entry_price - signal.stop_loss)
        if sl_distance <= 0:
            return None

        pip_distance = sl_distance / self.pip_value
        if pip_distance <= 0:
            return None

        lot_size = risk_amount / (pip_distance * self.pip_value_per_lot)
        lot_size = max(0.01, round(lot_size, 2))

        spread = self.spread_pips * self.pip_value
        slippage = self.slippage_pips * self.pip_value

        if signal.direction == Direction.LONG:
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
                "lot_size": lot_size,
                "commission_usd": round(commission, 2),
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

    def _close_trade(self, pos: Position, exit_time: datetime, exit_price: float) -> Trade:
        trade = pos.trade
        lot_size = pos.lot_size

        if trade.direction == Direction.LONG:
            price_diff = exit_price - trade.entry_price
        else:
            price_diff = trade.entry_price - exit_price

        pnl_pips = price_diff / self.pip_value if self.pip_value > 0 else 0.0
        pnl_usd = pnl_pips * self.pip_value_per_lot * lot_size

        trade.pnl = round(pnl_usd, 2)
        trade.pnl_pips = round(pnl_pips, 1)
        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.status = TradeStatus.CLOSED
        trade.metadata["pnl_usd"] = trade.pnl

        risk = abs(trade.entry_price - trade.stop_loss)
        if risk > 0:
            trade.risk_reward_achieved = round(price_diff / risk, 2)

        return trade

    def update_positions(self, bar: Bar, step_tracker: StepTracker | None = None) -> list[Trade]:
        closed: list[Trade] = []
        remaining: list[Position] = []

        for pos in self.open_positions:
            closed_trade: Trade | None = None

            if pos.is_sl_hit(bar):
                closed_trade = self._close_trade(pos, bar.time, pos.current_sl)
                if step_tracker:
                    step_tracker.add_step_to_trade(
                        closed_trade.id,
                        "Stop Loss Hit",
                        99,
                        bar.time,
                        pos.current_sl,
                        "",
                        f"Stop loss triggered at {pos.current_sl:.5f}",
                    )
            elif pos.is_tp_hit(bar):
                closed_trade = self._close_trade(pos, bar.time, pos.current_tp)
                if step_tracker:
                    step_tracker.add_step_to_trade(
                        closed_trade.id,
                        "Take Profit Hit",
                        100,
                        bar.time,
                        pos.current_tp,
                        "",
                        f"Take profit reached at {pos.current_tp:.5f}",
                    )

            if closed_trade:
                if step_tracker:
                    closed_trade.steps = step_tracker.get_trade_steps(closed_trade.id)
                self.closed_trades.append(closed_trade)
                closed.append(closed_trade)
            else:
                remaining.append(pos)

        self.open_positions = remaining
        return closed

    def has_open_position(self, strategy_id: str | None = None) -> bool:
        if strategy_id:
            return any(p.trade.strategy_id == strategy_id for p in self.open_positions)
        return len(self.open_positions) > 0

    def get_open_position(self, strategy_id: str) -> Optional[Position]:
        for pos in self.open_positions:
            if pos.trade.strategy_id == strategy_id:
                return pos
        return None

    def move_to_breakeven(
        self,
        strategy_id: str,
        bar: Bar,
        step_tracker: StepTracker | None = None,
    ):
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
