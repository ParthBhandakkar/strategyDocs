"""
Portfolio Manager — consistent USD PnL model across balance and stats.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade
from .broker import price_delta_to_usd


class Portfolio:
    """Tracks account balance, equity curve, and portfolio metrics."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance

    def on_trade_closed(self, trade: Trade):
        lot_size = float(trade.metadata.get("lot_size", 0.01))
        commission = float(trade.metadata.get("commission", 0.0))
        exit_price = trade.exit_price or trade.entry_price
        pnl_usd = price_delta_to_usd(
            trade.symbol,
            trade.pnl,
            lot_size,
            exit_price,
        )
        pnl_usd -= commission
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)
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
        return result
