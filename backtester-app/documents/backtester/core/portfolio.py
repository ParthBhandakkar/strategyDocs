"""
Portfolio Manager — consistent USD PnL model with commission.
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
        self._total_commission = 0.0

    def on_commission(self, commission: float):
        self._total_commission += commission
        self.balance -= commission

    def on_trade_closed(self, trade: Trade, broker: SimulatedBroker):
        """Update portfolio using lot-based USD PnL."""
        pos_lot = trade.metadata.get("lot_size", 0.01)
        pip_value_per_lot = broker.pip_value_per_lot_usd(trade.symbol)
        pnl_usd = trade.pnl_pips * pip_value_per_lot * pos_lot
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)
        trade.metadata["lot_size"] = pos_lot
        self.balance += pnl_usd
        self.trades.append(trade)

    def record_equity(self, timestamp: datetime):
        self.equity_curve.append({
            "time": timestamp.isoformat(),
            "equity": round(self.balance, 2),
        })
        if self.balance > self._peak_equity:
            self._peak_equity = self.balance

    def get_result(self) -> BacktestResult:
        result = BacktestResult(
            config=self.config,
            trades=self.trades,
            equity_curve=self.equity_curve,
        )
        result.compute_stats()
        result.total_pnl = round(self.balance - self.initial_balance, 2)
        return result
