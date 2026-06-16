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
        self._broker_ref: SimulatedBroker | None = None

    def attach_broker(self, broker: SimulatedBroker):
        self._broker_ref = broker

    def on_trade_closed(self, trade: Trade):
        """Update portfolio when a trade is closed using consistent USD PnL."""
        self.trades.append(trade)
        lot_size = float(trade.metadata.get("lot_size", 0.01))
        commission = float(trade.metadata.get("commission_usd", 0.0))

        pip_value = 0.0001
        pip_value_usd = 10.0
        if self._broker_ref is not None:
            self._broker_ref.set_pip_value(trade.symbol)
            pip_value = self._broker_ref.pip_value
            pip_value_usd = self._broker_ref.pip_value_usd_per_lot(trade.symbol)

        pnl_pips = trade.pnl / pip_value if pip_value > 0 else 0.0
        pnl_usd = (pnl_pips * pip_value_usd * lot_size) - commission
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)
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
