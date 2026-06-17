"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade
from .broker import SimulatedBroker


class Portfolio:
    """Tracks account balance, equity curve, and computes portfolio metrics."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance

    def on_commission(self, commission: float):
        self.balance -= commission

    def on_trade_closed(self, trade: Trade, broker: SimulatedBroker | None = None):
        self.trades.append(trade)
        pnl_usd = trade.pnl
        if broker is not None and pnl_usd == 0 and trade.pnl_pips:
            pos_lot = trade.metadata.get("lot_size", 0.01)
            pnl_usd = trade.pnl_pips * broker.pip_value_per_lot * pos_lot
            trade.pnl = pnl_usd
        self.balance += pnl_usd
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)

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
