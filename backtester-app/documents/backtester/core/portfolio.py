"""
Portfolio Manager — consistent USD PnL model across balance and stats.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade
from .broker import pip_size_for_symbol, pip_value_per_lot_usd


class Portfolio:
    """Tracks account balance, equity curve, and computes portfolio metrics."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance

    def _trade_pnl_usd(self, trade: Trade) -> float:
        lot_size = float(trade.metadata.get("lot_size", 0.01))
        commission = float(trade.metadata.get("commission", 0.0))
        pip_size = pip_size_for_symbol(trade.symbol)
        pip_value = pip_value_per_lot_usd(trade.symbol)
        pnl_pips = trade.pnl / pip_size if pip_size > 0 else 0.0
        return (pnl_pips * pip_value * lot_size) - commission

    def on_trade_closed(self, trade: Trade) -> None:
        pnl_usd = self._trade_pnl_usd(trade)
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)
        trade.pnl = pnl_usd
        self.trades.append(trade)
        self.balance += pnl_usd

    def record_equity(self, timestamp: datetime) -> None:
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
