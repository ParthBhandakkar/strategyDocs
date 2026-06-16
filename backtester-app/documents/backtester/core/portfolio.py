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
        lot_size = float(trade.metadata.get("lot_size", 0.01))
        pip_distance = trade.pnl / self._pip_value_for_symbol(trade.symbol)
        pnl_usd = pip_distance * self._pip_value_per_lot(trade.symbol) * lot_size
        commission = float(trade.metadata.get("commission", 0.0))
        pnl_usd -= commission
        self.balance += pnl_usd
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)

    def _pip_value_for_symbol(self, symbol: str) -> float:
        sym = symbol.upper()
        if "JPY" in sym:
            return 0.01
        if "XAU" in sym or "GOLD" in sym:
            return 0.1
        if "XAG" in sym or "SILVER" in sym:
            return 0.01
        if "BTC" in sym or "ETH" in sym:
            return 1.0
        return 0.0001

    @staticmethod
    def _pip_value_per_lot(symbol: str) -> float:
        sym = symbol.upper()
        if "JPY" in sym:
            return 6.5
        if "XAU" in sym or "GOLD" in sym:
            return 10.0
        if "XAG" in sym or "SILVER" in sym:
            return 50.0
        if "BTC" in sym or "ETH" in sym:
            return 1.0
        return 10.0

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
