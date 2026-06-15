"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
Uses consistent USD PnL from lot size, pip value, and commission.
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

    def on_trade_closed(self, trade: Trade, symbol: str):
        """Update portfolio when a trade is closed."""
        self.trades.append(trade)
        if "pnl_usd" not in trade.metadata:
            pip_usd = pip_value_per_lot_usd(symbol)
            lot_size = trade.metadata.get("lot_size", 0.01)
            commission = trade.metadata.get("commission", 0.0)
            gross = trade.pnl_pips * pip_usd * lot_size
            trade.metadata["pnl_usd"] = round(gross - commission, 2)

        pnl_usd = trade.metadata["pnl_usd"]
        trade.pnl = pnl_usd
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
