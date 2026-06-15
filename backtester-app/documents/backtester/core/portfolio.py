"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
Uses consistent USD PnL from lot size and pip value.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade, Direction


class Portfolio:
    """Tracks account balance, equity curve, and computes portfolio metrics."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance

    def on_trade_closed(self, trade: Trade, broker, exit_commission: bool = False):
        """Update portfolio when a trade is closed using lot-based USD PnL."""
        lot_size = trade.metadata.get("lot_size", 0.01)
        pip_value_per_lot = broker.get_usd_per_pip(lot_size)
        pnl_pips = trade.pnl / broker.pip_value if broker.pip_value > 0 else 0.0
        pnl_usd = pnl_pips * pip_value_per_lot

        entry_commission = trade.metadata.get("commission", 0.0)
        exit_comm = broker.commission_per_lot * lot_size if exit_commission else 0.0
        net_pnl = pnl_usd - entry_commission - exit_comm

        trade.pnl_pips = round(pnl_pips, 1)
        trade.metadata["pnl_usd"] = round(net_pnl, 2)
        trade.pnl = net_pnl

        self.trades.append(trade)
        self.balance += net_pnl

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
