"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
Uses a consistent USD PnL model aligned with broker lot sizing.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade


class Portfolio:
    """Tracks account balance, equity curve, and portfolio metrics."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance

    def on_trade_closed(self, trade: Trade) -> None:
        self.trades.append(trade)
        pnl_usd = trade.metadata.get("pnl_usd", trade.pnl)
        self.balance += pnl_usd

    def record_equity(self, timestamp: datetime) -> None:
        self.equity_curve.append(
            {"time": timestamp.isoformat(), "equity": round(self.balance, 2)}
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
