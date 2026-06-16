"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
Uses consistent USD PnL from price delta, pip value, and lot size.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade
from .broker import pip_value_per_lot_usd


class Portfolio:
    """Tracks account balance, equity curve, and computes portfolio metrics."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance

    def on_trade_closed(self, trade: Trade, lot_size: float = 0.01, commission: float = 0.0):
        """Update portfolio when a trade is closed."""
        pip_per_lot = pip_value_per_lot_usd(trade.symbol)
        pnl_usd = trade.pnl_pips * pip_per_lot * lot_size - commission
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)
        trade.metadata["lot_size"] = lot_size
        self.trades.append(trade)
        self.balance += pnl_usd

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
        return result
