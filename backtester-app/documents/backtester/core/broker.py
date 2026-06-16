"""
Simulated Broker — handles order execution, fill simulation, SL/TP management.
"""

from __future__ import annotations

from typing import Optional

from . import Bar, Signal, Trade, Position, Direction, OrderType, TradeStatus
from .events import FillEvent
from .step_tracker import StepTracker


def pip_size(symbol: str) -> float:
    """Return price increment treated as one pip/point for the symbol."""
    sym = symbol.upper()
    if "JPY" in sym and "XAU" not in sym:
        return 0.01
    if "XAU" in sym or "GOLD" in sym:
        return 0.1
    if "XAG" in sym or "SILVER" in sym:
        return 0.01
    if "BTC" in sym or "ETH" in sym:
        return 1.0
    return 0.0001


def pip_value_per_lot(symbol: str, price: float | None = None) -> float:
    """Approximate USD value of one pip/point for one standard lot."""
    sym = symbol.upper()
    if "XAU" in sym:
        return 10.0
    if "XAG" in sym:
        return 50.0
    if "BTC" in sym:
        return 1.0
    if "ETH" in sym:
        return 0.1
    if sym.endswith("JPY") or "JPY" in sym:
        px = price or 150.0
        return 100000.0 / px / 100.0
    return 10.0


class SimulatedBroker:
    """Simulates order execution with spread, slippage, and commission."""

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
        self.symbol = ""
        self._next_trade_id = 1
        self.open_positions: list[Position] = []
        self.closed_trades: list[Trade] = []

    def set_pip_value(self, symbol: str):
        self.symbol = symbol
        self.pip_value = pip_size(symbol)

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

        dollars_per_pip = pip_value_per_lot(signal.symbol, signal.entry_price)
        lot_size = risk_amount / (pip_distance * dollars_per_pip)
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
                **signal.metadata,
                "lot_size": lot_size,
                "commission": commission,
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

    def _close_trade_usd(self, trade: Trade, exit_price: float) -> float:
        lot_size = float(trade.metadata.get("lot_size", 0.01))
        commission = float(trade.metadata.get("commission", 0.0))
        trade.close(trade.exit_time, exit_price, self.pip_value)
        dollars_per_pip = pip_value_per_lot(trade.symbol, exit_price)
        pnl_usd = trade.pnl_pips * dollars_per_pip * lot_size - commission
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)
        trade.pnl = pnl_usd
        return pnl_usd

    def update_positions(self, bar: Bar, step_tracker: StepTracker | None = None) -> list[Trade]:
        closed: list[Trade] = []
        remaining: list[Position] = []

        for pos in self.open_positions:
            trade = pos.trade
            closed_trade: Trade | None = None

            if pos.is_sl_hit(bar):
                exit_price = pos.current_sl
                trade.exit_time = bar.time
                self._close_trade_usd(trade, exit_price)
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
            elif pos.is_tp_hit(bar):
                exit_price = pos.current_tp
                trade.exit_time = bar.time
                self._close_trade_usd(trade, exit_price)
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

    def move_to_breakeven(self, strategy_id: str, bar: Bar, step_tracker: StepTracker | None = None):
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
