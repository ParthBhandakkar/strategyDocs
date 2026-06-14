"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
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
        # Simple PnL: for proper lot-based PnL, multiply by lot_size * contract_size
        # Here we use risk-based PnL: risk_amount * RR_achieved
        risk_amount = self.initial_balance * self.config.risk_per_trade
        if trade.risk_reward_achieved != 0:
            pnl_usd = risk_amount * trade.risk_reward_achieved
        else:
            pnl_usd = trade.pnl * 10000  # Rough conversion for testing
        self.balance += pnl_usd
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)

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
