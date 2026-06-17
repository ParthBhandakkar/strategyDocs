"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
Uses a consistent USD PnL model across balance, equity curve, and stats.
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

    def _trade_pnl_usd(self, trade: Trade) -> float:
        lot_size = float(trade.metadata.get("lot_size", 0.01))
        commission = float(trade.metadata.get("commission", 0.0))
        pip_value = float(trade.metadata.get("pip_value", 0.0001))
        pip_value_per_lot = float(trade.metadata.get("pip_value_per_lot", 10.0))

        if trade.exit_price is None:
            return 0.0

        if trade.direction.value == "LONG":
            price_delta = trade.exit_price - trade.entry_price
        else:
            price_delta = trade.entry_price - trade.exit_price

        pips = price_delta / pip_value if pip_value > 0 else 0.0
        gross = pips * pip_value_per_lot * lot_size
        return round(gross - commission, 2)

    def on_trade_closed(self, trade: Trade):
        """Update portfolio when a trade is closed."""
        pnl_usd = self._trade_pnl_usd(trade)
        trade.metadata["price_pnl"] = trade.pnl
        trade.metadata["pnl_usd"] = pnl_usd
        trade.pnl = pnl_usd

        risk = abs(trade.entry_price - trade.stop_loss)
        if risk > 0 and trade.exit_price is not None:
            if trade.direction.value == "LONG":
                price_delta = trade.exit_price - trade.entry_price
            else:
                price_delta = trade.entry_price - trade.exit_price
            trade.risk_reward_achieved = round(price_delta / risk, 2)

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
