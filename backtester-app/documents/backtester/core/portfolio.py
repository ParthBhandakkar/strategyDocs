"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
Uses consistent USD PnL from broker lot-based calculations.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade
from .broker import SimulatedBroker


class Portfolio:
    """Tracks account balance, equity curve, and computes portfolio metrics."""

    def __init__(self, config: BacktestConfig, broker: SimulatedBroker | None = None):
        self.config = config
        self.broker = broker
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance

    def on_trade_closed(self, trade: Trade):
        self.trades.append(trade)
        if self.broker:
            pnl_usd = self.broker.compute_trade_pnl_usd(trade)
        else:
            risk_amount = self.initial_balance * self.config.risk_per_trade
            pnl_usd = risk_amount * trade.risk_reward_achieved
        self.balance += pnl_usd
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)

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
        result.compute_stats(self.broker)
        return result
