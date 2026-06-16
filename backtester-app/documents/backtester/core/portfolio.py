"""
Portfolio manager with consistent USD PnL accounting.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade


class Portfolio:
    """Tracks balance, equity curve, and trade-level USD PnL."""

    def __init__(self, config: BacktestConfig, pip_value: float = 0.0001):
        self.config = config
        self.pip_value = pip_value
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance

    def on_trade_closed(self, trade: Trade):
        lot_size = float(trade.metadata.get("lot_size", 0.01))
        pip_distance = trade.pnl / self.pip_value if self.pip_value > 0 else 0.0
        pip_value_per_lot = 10.0
        pnl_usd = pip_distance * pip_value_per_lot * lot_size
        commission = float(trade.metadata.get("commission", 0.0))
        pnl_usd -= commission

        trade.pnl = pnl_usd
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)
        self.trades.append(trade)
        self.balance += pnl_usd

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
