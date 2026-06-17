"""
Simulated broker with symbol-aware pip sizing and USD PnL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from . import Bar, Signal, Trade, Position, Direction, TradeStatus
from .events import FillEvent
from .step_tracker import StepTracker


@dataclass(frozen=True)
class SymbolSpec:
    pip_size: float
    pip_value_per_lot: float
    min_lot: float = 0.01


SYMBOL_SPECS: dict[str, SymbolSpec] = {
    "DEFAULT": SymbolSpec(pip_size=0.0001, pip_value_per_lot=10.0),
    "JPY": SymbolSpec(pip_size=0.01, pip_value_per_lot=6.5),
    "XAUUSD": SymbolSpec(pip_size=0.1, pip_value_per_lot=10.0),
    "XAGUSD": SymbolSpec(pip_size=0.01, pip_value_per_lot=50.0),
    "BTCUSD": SymbolSpec(pip_size=1.0, pip_value_per_lot=1.0),
    "ETHUSD": SymbolSpec(pip_size=0.1, pip_value_per_lot=1.0),
}


def get_symbol_spec(symbol: str) -> SymbolSpec:
    sym = symbol.upper()
    if sym in SYMBOL_SPECS:
        return SYMBOL_SPECS[sym]
    if "JPY" in sym:
        return SYMBOL_SPECS["JPY"]
    if "XAU" in sym or sym == "GOLD":
        return SYMBOL_SPECS["XAUUSD"]
    if "XAG" in sym or sym == "SILVER":
        return SYMBOL_SPECS["XAGUSD"]
    if "BTC" in sym:
        return SYMBOL_SPECS["BTCUSD"]
    if "ETH" in sym:
        return SYMBOL_SPECS["ETHUSD"]
    return SYMBOL_SPECS["DEFAULT"]


class SimulatedBroker:
    """Simulates fills, spread, slippage, commission, and SL/TP management."""

    def __init__(
        self,
        spread_pips: float = 1.0,
        slippage_pips: float = 0.5,
        commission_per_lot: float = 7.0,
        symbol: str = "EURUSD",
    ):
        self.spread_pips = spread_pips
        self.slippage_pips = slippage_pips
        self.commission_per_lot = commission_per_lot
        self.symbol = symbol
        self.spec = get_symbol_spec(symbol)
        self.pip_value = self.spec.pip_size
        self._next_trade_id = 1
        self.open_positions: list[Position] = []
        self.closed_trades: list[Trade] = []

    def set_pip_value(self, symbol: str):
        self.symbol = symbol
        self.spec = get_symbol_spec(symbol)
        self.pip_value = self.spec.pip_size

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

        pip_distance = sl_distance / self.spec.pip_size
        if pip_distance <= 0:
            return None

        lot_size = risk_amount / (pip_distance * self.spec.pip_value_per_lot)
        lot_size = max(self.spec.min_lot, round(lot_size, 2))

        spread = self.spread_pips * self.spec.pip_size
        slippage = self.slippage_pips * self.spec.pip_size

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
                "pip_value_per_lot": self.spec.pip_value_per_lot,
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

    def update_positions(self, bar: Bar, step_tracker: StepTracker | None = None) -> list[Trade]:
        closed: list[Trade] = []
        remaining: list[Position] = []

        for pos in self.open_positions:
            trade = pos.trade
            closed_trade: Trade | None = None

            if pos.is_sl_hit(bar):
                exit_price = pos.current_sl
                self._close_trade(trade, bar.time, exit_price)
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
                self._close_trade(trade, bar.time, exit_price)
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

    def _close_trade(self, trade: Trade, exit_time: datetime, exit_price: float):
        trade.close(exit_time, exit_price, self.spec.pip_size)
        lot_size = float(trade.metadata.get("lot_size", 0.01))
        pip_value_per_lot = float(trade.metadata.get("pip_value_per_lot", self.spec.pip_value_per_lot))
        commission = float(trade.metadata.get("commission", 0.0))
        gross_pnl = trade.pnl_pips * pip_value_per_lot * lot_size
        trade.metadata["pnl_usd"] = round(gross_pnl - commission, 2)

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

    def force_close_all(self, bar: Bar):
        for pos in list(self.open_positions):
            self._close_trade(pos.trade, bar.time, bar.close)
            self.closed_trades.append(pos.trade)
        self.open_positions.clear()
