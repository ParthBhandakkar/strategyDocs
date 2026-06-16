"""
Portfolio Manager — tracks USD balance, equity, and drawdown.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade


class Portfolio:
    """Tracks account balance using broker USD PnL and commissions."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance

    def on_fill(self, commission_usd: float):
        self.balance -= commission_usd

    def on_trade_closed(self, trade: Trade):
        self.trades.append(trade)
        self.balance += trade.pnl

    def record_equity(self, timestamp: datetime):
        self.equity_curve.append(
            {
                "time": timestamp.isoformat(),
                "equity": round(self.balance, 2),
            }
        )
        if self.balance > self._peak_equity:
            self._peak_equity = self.balance

    def get_result(self) -> BacktestResult:
        result = BacktestResult(
            config=self.config,
            trades=self.trades,
            equity_curve=self.equity_curve,
        )
        result.compute_stats()
        return result
