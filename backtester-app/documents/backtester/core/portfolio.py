"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
Uses consistent USD PnL via broker lot sizing.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade
from .broker import SimulatedBroker


class Portfolio:
    """Tracks account balance, equity curve, and computes portfolio metrics."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance
        self._trade_lots: dict[int, float] = {}
        self._entry_commissions: dict[int, float] = {}

    def on_trade_opened(self, trade_id: int, lot_size: float, commission: float):
        self._trade_lots[trade_id] = lot_size
        self._entry_commissions[trade_id] = commission

    def on_trade_closed(self, trade: Trade, lot_size: float, exit_commission: float):
        self.trades.append(trade)
        self._trade_lots[trade.id] = lot_size
        entry_comm = self._entry_commissions.get(trade.id, 0.0)
        trade.metadata["lot_size"] = lot_size
        trade.metadata["commission_usd"] = round(entry_comm + exit_commission, 2)

    def finalize_pnl(self, broker: SimulatedBroker):
        for trade in self.trades:
            lot_size = self._trade_lots.get(trade.id, 0.01)
            commission = float(trade.metadata.get("commission_usd", 0.0))
            pnl_usd = broker.usd_pnl(trade, lot_size) - commission
            trade.metadata["pnl_usd"] = round(pnl_usd, 2)
            trade.pnl = pnl_usd

    def rebuild_balance(self):
        self.balance = self.initial_balance
        for trade in self.trades:
            self.balance += trade.pnl

    def record_equity(self, timestamp: datetime):
        self.equity_curve.append({
            "time": timestamp.isoformat(),
            "equity": round(self.balance, 2),
        })
        if self.balance > self._peak_equity:
            self._peak_equity = self.balance

    def get_result(self, broker: SimulatedBroker | None = None) -> BacktestResult:
        if broker is not None:
            self.finalize_pnl(broker)
            self.rebuild_balance()
            if self.equity_curve:
                self.equity_curve[-1]["equity"] = round(self.balance, 2)
            elif self.trades:
                last_trade = self.trades[-1]
                exit_time = last_trade.exit_time or last_trade.entry_time
                self.record_equity(exit_time)

        result = BacktestResult(
            config=self.config,
            trades=self.trades,
            equity_curve=self.equity_curve,
        )
        result.compute_stats()
        return result
