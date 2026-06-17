"""
Simulated Broker — order execution, symbol-aware sizing, SL/TP management.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import Bar, Signal, Trade, Position, Direction, OrderType, TradeStatus
from .events import FillEvent
from .step_tracker import StepTracker


@dataclass(frozen=True)
class SymbolSpec:
    pip_size: float
    usd_per_pip_per_lot: float
    min_lot: float = 0.01


def get_symbol_spec(symbol: str) -> SymbolSpec:
    sym = symbol.upper()
    if "XAU" in sym or "GOLD" in sym:
        return SymbolSpec(pip_size=0.1, usd_per_pip_per_lot=10.0)
    if "XAG" in sym or "SILVER" in sym:
        return SymbolSpec(pip_size=0.01, usd_per_pip_per_lot=50.0)
    if "BTC" in sym:
        return SymbolSpec(pip_size=1.0, usd_per_pip_per_lot=1.0)
    if "ETH" in sym:
        return SymbolSpec(pip_size=0.1, usd_per_pip_per_lot=1.0)
    if "JPY" in sym:
        return SymbolSpec(pip_size=0.01, usd_per_pip_per_lot=6.5)
    return SymbolSpec(pip_size=0.0001, usd_per_pip_per_lot=10.0)


class SimulatedBroker:
    """Simulates fills with spread, slippage, commission, and USD PnL."""

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

    def price_to_pips(self, price_distance: float) -> float:
        if self.pip_value <= 0:
            return 0.0
        return price_distance / self.pip_value

    def pips_to_usd(self, pips: float, lot_size: float) -> float:
        return pips * self.spec.usd_per_pip_per_lot * lot_size

    def compute_lot_size(self, balance: float, risk_per_trade: float, sl_distance: float) -> float:
        risk_amount = balance * risk_per_trade
        pip_distance = self.price_to_pips(sl_distance)
        if pip_distance <= 0:
            return 0.0
        lot_size = risk_amount / (pip_distance * self.spec.usd_per_pip_per_lot)
        return max(self.spec.min_lot, round(lot_size, 2))

    def compute_trade_pnl_usd(self, trade: Trade, lot_size: float) -> float:
        if trade.exit_price is None:
            return 0.0
        if trade.direction == Direction.LONG:
            price_move = trade.exit_price - trade.entry_price
        else:
            price_move = trade.entry_price - trade.exit_price
        pips = self.price_to_pips(price_move)
        gross = self.pips_to_usd(pips, lot_size)
        commission = self.commission_per_lot * lot_size
        return gross - commission

    def execute_signal(
        self,
        signal: Signal,
        current_bar: Bar,
        balance: float,
        risk_per_trade: float = 0.01,
    ) -> Optional[FillEvent]:
        sl_distance = abs(signal.entry_price - signal.stop_loss)
        if sl_distance <= 0:
            return None

        lot_size = self.compute_lot_size(balance, risk_per_trade, sl_distance)
        if lot_size <= 0:
            return None

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
            metadata={**signal.metadata, "lot_size": lot_size, "commission": commission},
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
                trade.close(bar.time, exit_price, self.pip_value)
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
                trade.close(bar.time, exit_price, self.pip_value)
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
                pnl_usd = self.compute_trade_pnl_usd(closed_trade, pos.lot_size)
                closed_trade.metadata["pnl_usd"] = round(pnl_usd, 2)
                closed_trade.pnl = pnl_usd
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

    def force_close_all(self, bar: Bar) -> list[Trade]:
        closed: list[Trade] = []
        for pos in list(self.open_positions):
            pos.trade.close(bar.time, bar.close, self.pip_value)
            pnl_usd = self.compute_trade_pnl_usd(pos.trade, pos.lot_size)
            pos.trade.metadata["pnl_usd"] = round(pnl_usd, 2)
            pos.trade.pnl = pnl_usd
            self.closed_trades.append(pos.trade)
            closed.append(pos.trade)
        self.open_positions.clear()
        return closed
