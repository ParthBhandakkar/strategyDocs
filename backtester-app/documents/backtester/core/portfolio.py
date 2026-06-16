"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
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

    def _trade_pnl_usd(self, trade: Trade) -> float:
        if trade.exit_price is None:
            return 0.0
        lot_size = float(trade.metadata.get("lot_size", 0.01))
        contract_size = float(trade.metadata.get("contract_size", 100_000.0))
        commission = float(trade.metadata.get("commission_usd", 0.0))

        if trade.direction == Direction.LONG:
            price_delta = trade.exit_price - trade.entry_price
        else:
            price_delta = trade.entry_price - trade.exit_price

        gross = price_delta * contract_size * lot_size
        return gross - commission

    def on_trade_closed(self, trade: Trade):
        """Update portfolio when a trade is closed."""
        pnl_usd = self._trade_pnl_usd(trade)
        trade.pnl = pnl_usd
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)
        self.trades.append(trade)
        self.balance += pnl_usd

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
