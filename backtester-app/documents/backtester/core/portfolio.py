"""
Portfolio Manager — consistent USD PnL model for balance and stats.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade


def trade_pnl_usd(trade: Trade) -> float:
    """Convert price-based PnL to USD using stored lot and symbol specs."""
    lot_size = float(trade.metadata.get("lot_size", 0.01))
    pip_value = float(trade.metadata.get("pip_value", 0.0001))
    dollar_per_pip = float(trade.metadata.get("dollar_per_pip_per_lot", 10.0))
    commission = float(trade.metadata.get("commission", 0.0))

    if pip_value <= 0:
        return 0.0

    pip_move = trade.pnl / pip_value
    return round(pip_move * dollar_per_pip * lot_size - commission, 2)


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
        pnl_usd = trade_pnl_usd(trade)
        trade.metadata["pnl_usd"] = pnl_usd
        trade.pnl = pnl_usd
        self.trades.append(trade)
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
