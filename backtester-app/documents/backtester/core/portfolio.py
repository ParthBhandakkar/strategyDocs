"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
Uses consistent USD PnL from broker lot-based calculations.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade


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
        self.trades.append(trade)
        pnl_usd = trade.metadata.get("pnl_usd")
        if pnl_usd is None:
            risk_amount = self.initial_balance * self.config.risk_per_trade
            pnl_usd = risk_amount * trade.risk_reward_achieved
            trade.metadata["pnl_usd"] = round(pnl_usd, 2)
        self.balance += float(pnl_usd)

    def record_equity(self, timestamp: datetime):
        """Record a point on the equity curve."""
        self.equity_curve.append({
            "time": timestamp.isoformat(),
            "equity": round(self.balance, 2),
        })
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
