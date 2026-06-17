"""
Simulated Broker — order execution, fill simulation, SL/TP management.
Symbol-aware pip sizing for comparable risk across instruments.
"""

from __future__ import annotations

from typing import Optional

from . import Bar, Signal, Trade, Position, Direction, TradeStatus
from .events import FillEvent
from .step_tracker import StepTracker


def pip_size_for_symbol(symbol: str) -> float:
    sym = symbol.upper()
    if "JPY" in sym:
        return 0.01
    if "XAU" in sym or "GOLD" in sym:
        return 0.1
    if "XAG" in sym or "SILVER" in sym:
        return 0.01
    if sym in {"BTCUSD", "ETHUSD"}:
        return 1.0
    return 0.0001


def pip_value_per_lot(symbol: str, price: float | None = None) -> float:
    """Approximate USD value of one pip for one standard lot."""
    sym = symbol.upper()
    if "XAU" in sym:
        return 10.0
    if "XAG" in sym:
        return 50.0
    if sym in {"BTCUSD", "ETHUSD"}:
        return 1.0
    if "JPY" in sym and price and price > 0:
        return 1000.0 / price
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

    def set_pip_value(self, symbol: str) -> None:
        self.symbol = symbol.upper()
        self.pip_value = pip_size_for_symbol(symbol)

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

        pip_val = pip_value_per_lot(signal.symbol, signal.entry_price)
        lot_size = risk_amount / (pip_distance * pip_val)
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
                "pip_value_per_lot": pip_val,
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

    def update_positions(
        self, bar: Bar, step_tracker: StepTracker | None = None
    ) -> list[Trade]:
        closed: list[Trade] = []
        remaining: list[Position] = []

        for pos in self.open_positions:
            trade = pos.trade
            closed_trade: Trade | None = None

            if pos.is_sl_hit(bar):
                trade.close(bar.time, pos.current_sl, self.pip_value)
                self._apply_usd_pnl(trade, pos.lot_size)
                closed_trade = trade
                if step_tracker:
                    step_tracker.add_step_to_trade(
                        trade.id,
                        "Stop Loss Hit",
                        99,
                        bar.time,
                        pos.current_sl,
                        "",
                        f"Stop loss triggered at {pos.current_sl:.5f}",
                    )
            elif pos.is_tp_hit(bar):
                trade.close(bar.time, pos.current_tp, self.pip_value)
                self._apply_usd_pnl(trade, pos.lot_size)
                closed_trade = trade
                if step_tracker:
                    step_tracker.add_step_to_trade(
                        trade.id,
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

    def _apply_usd_pnl(self, trade: Trade, lot_size: float) -> None:
        pip_val = trade.metadata.get(
            "pip_value_per_lot", pip_value_per_lot(trade.symbol, trade.entry_price)
        )
        trade.pnl = trade.pnl_pips * pip_val * lot_size
        commission = trade.metadata.get("commission", 0.0)
        trade.pnl -= commission
        trade.metadata["pnl_usd"] = round(trade.pnl, 2)

    def has_open_position(self, strategy_id: str | None = None) -> bool:
        if strategy_id:
            return any(p.trade.strategy_id == strategy_id for p in self.open_positions)
        return len(self.open_positions) > 0

    def get_open_position(self, strategy_id: str) -> Optional[Position]:
        for pos in self.open_positions:
            if pos.trade.strategy_id == strategy_id:
                return pos
        return None
