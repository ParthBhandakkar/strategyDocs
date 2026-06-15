"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
Uses a consistent USD PnL model based on lot size and pip value.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade


def trade_pnl_usd(trade: Trade) -> float:
    lot_size = float(trade.metadata.get("lot_size", 0.01))
    pip_value = float(trade.metadata.get("pip_value", 0.0001))
    pip_value_per_lot = float(trade.metadata.get("pip_value_per_lot", 10.0))
    commission = float(trade.metadata.get("commission", 0.0))
    if pip_value <= 0:
        return -commission
    pips = trade.pnl / pip_value
    return round(pips * pip_value_per_lot * lot_size - commission, 2)


class Portfolio:
    """Tracks account balance, equity curve, and computes portfolio metrics."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance

    def on_trade_closed(self, trade: Trade):
        """Update portfolio when a trade is closed."""
        pnl_usd = trade_pnl_usd(trade)
        trade.metadata["pnl_usd"] = pnl_usd
        self.trades.append(trade)
        self.balance += pnl_usd

    def record_equity(self, timestamp: datetime):
        """Record a point on the equity curve."""
        self.equity_curve.append(
            {
                "time": timestamp.isoformat(),
                "equity": round(self.balance, 2),
            }
        )
        if self.balance > self._peak_equity:
            self._peak_equity = self.balance

    def get_result(self) -> BacktestResult:
        """Generate the final backtest result with computed statistics."""
        result = BacktestResult(
            config=self.config,
            trades=self.trades,
            equity_curve=self.equity_curve,
        )
        result.compute_stats()
        return result
