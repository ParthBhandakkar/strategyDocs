"""
Simulated Broker — order execution, fill simulation, SL/TP management.
Symbol-aware pip/point sizing for comparable risk across instruments.
"""

from __future__ import annotations

from typing import Optional

from . import Bar, Signal, Trade, Position, Direction, TradeStatus
from .events import FillEvent
from .step_tracker import StepTracker


class SimulatedBroker:
    """Simulates order execution with spread, slippage, and commission."""

    def __init__(
        self,
        spread_pips: float = 1.0,
        slippage_pips: float = 0.5,
        commission_per_lot: float = 7.0,
    ):
        self.spread_pips = spread_pips
        self.slippage_pips = slippage_pips
        self.commission_per_lot = commission_per_lot
        self.symbol = "EURUSD"
        self.pip_size = 0.0001
        self.contract_size = 100_000.0
        self.usd_per_pip_per_lot = 10.0
        self._next_trade_id = 1
        self.open_positions: list[Position] = []
        self.closed_trades: list[Trade] = []

    def set_symbol(self, symbol: str):
        self.symbol = symbol.upper()
        specs = _symbol_specs(self.symbol)
        self.pip_size = specs["pip_size"]
        self.contract_size = specs["contract_size"]
        self.usd_per_pip_per_lot = specs["usd_per_pip_per_lot"]

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

        pip_distance = sl_distance / self.pip_size
        if pip_distance <= 0:
            return None

        lot_size = risk_amount / (pip_distance * self.usd_per_pip_per_lot)
        lot_size = max(0.01, round(lot_size, 2))

        spread = self.spread_pips * self.pip_size
        slippage = self.slippage_pips * self.pip_size

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
            lot_size=lot_size,
            metadata=signal.metadata.copy(),
        )
        trade.metadata["commission"] = commission
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
            closed_trade = None

            if pos.is_sl_hit(bar):
                exit_price = pos.current_sl
                trade.close(
                    bar.time,
                    exit_price,
                    self.pip_size,
                    pos.lot_size,
                    self.contract_size,
                    trade.metadata.get("commission", 0.0),
                )
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
                trade.close(
                    bar.time,
                    exit_price,
                    self.pip_size,
                    pos.lot_size,
                    self.contract_size,
                    trade.metadata.get("commission", 0.0),
                )
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


def _symbol_specs(symbol: str) -> dict[str, float]:
    sym = symbol.upper()
    if "JPY" in sym:
        return {"pip_size": 0.01, "contract_size": 100_000.0, "usd_per_pip_per_lot": 6.5}
    if "XAU" in sym or "GOLD" in sym:
        return {"pip_size": 0.1, "contract_size": 100.0, "usd_per_pip_per_lot": 10.0}
    if "XAG" in sym or "SILVER" in sym:
        return {"pip_size": 0.01, "contract_size": 5_000.0, "usd_per_pip_per_lot": 50.0}
    if sym in {"BTCUSD", "ETHUSD"}:
        return {"pip_size": 1.0, "contract_size": 1.0, "usd_per_pip_per_lot": 1.0}
    return {"pip_size": 0.0001, "contract_size": 100_000.0, "usd_per_pip_per_lot": 10.0}
