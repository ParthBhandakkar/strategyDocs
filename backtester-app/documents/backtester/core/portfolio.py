"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade


class Portfolio:
    """Tracks account balance with consistent USD PnL."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance

    def on_trade_open_commission(self, commission: float):
        self.balance -= commission

    def on_trade_closed(self, trade: Trade):
        pnl_usd = trade.metadata.get("pnl_usd")
        if pnl_usd is None:
            lot_size = trade.metadata.get("lot_size", 0.01)
            pnl_usd = trade.pnl_pips * 10.0 * lot_size
            trade.metadata["pnl_usd"] = round(pnl_usd, 2)
        trade.pnl = float(pnl_usd)
        self.trades.append(trade)
        self.balance += float(pnl_usd)

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
