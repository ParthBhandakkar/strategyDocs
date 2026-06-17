"""
Simulated Broker — handles order execution, fill simulation, SL/TP management.
Symbol-aware pip sizing with consistent USD PnL.
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
        pip_value: float = 0.0001,
    ):
        self.spread_pips = spread_pips
        self.slippage_pips = slippage_pips
        self.commission_per_lot = commission_per_lot
        self.pip_value = pip_value
        self._next_trade_id = 1
        self.open_positions: list[Position] = []
        self.closed_trades: list[Trade] = []

    def set_pip_value(self, symbol: str) -> None:
        sym = symbol.upper()
        if "JPY" in sym:
            self.pip_value = 0.01
        elif "XAU" in sym or "GOLD" in sym:
            self.pip_value = 0.1
        elif "XAG" in sym or "SILVER" in sym:
            self.pip_value = 0.01
        elif sym in {"BTCUSD", "ETHUSD"}:
            self.pip_value = 1.0
        else:
            self.pip_value = 0.0001

    @staticmethod
    def pip_value_per_lot(symbol: str) -> float:
        sym = symbol.upper()
        if "JPY" in sym:
            return 6.67
        if "XAU" in sym or "GOLD" in sym:
            return 1.0
        if "XAG" in sym or "SILVER" in sym:
            return 5.0
        if sym in {"BTCUSD", "ETHUSD"}:
            return 1.0
        return 10.0

    def usd_pnl(self, symbol: str, price_move: float, lot_size: float) -> float:
        pips = price_move / self.pip_value if self.pip_value else 0.0
        return pips * self.pip_value_per_lot(symbol) * lot_size

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

        dollars_per_pip = self.pip_value_per_lot(signal.symbol)
        lot_size = risk_amount / (pip_distance * dollars_per_pip)
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

    def update_positions(
        self,
        bar: Bar,
        step_tracker: StepTracker | None = None,
        symbol: str = "",
    ) -> list[Trade]:
        closed: list[Trade] = []
        remaining: list[Position] = []

        for pos in self.open_positions:
            trade = pos.trade
            closed_trade: Trade | None = None
            sym = symbol or trade.symbol
            commission = float(trade.metadata.get("commission", 0.0))

            if pos.is_sl_hit(bar):
                exit_price = pos.current_sl
                trade.close(
                    bar.time,
                    exit_price,
                    self.pip_value,
                    pos.lot_size,
                    self.pip_value_per_lot(sym),
                    commission,
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
                    self.pip_value,
                    pos.lot_size,
                    self.pip_value_per_lot(sym),
                    commission,
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
            return any(pos.trade.strategy_id == strategy_id for pos in self.open_positions)
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
    ) -> None:
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
