"""
Portfolio Manager — tracks equity, drawdown, and generates equity curve.
Uses a consistent USD PnL model based on lot size and price movement.
"""

from __future__ import annotations

from datetime import datetime

from . import BacktestConfig, BacktestResult, Trade
from .broker import dollars_per_lot_per_point


class Portfolio:
    """Tracks account balance, equity curve, and computes portfolio metrics."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.initial_balance = config.initial_balance
        self.balance = config.initial_balance
        self.equity_curve: list[dict] = []
        self.trades: list[Trade] = []
        self._peak_equity = config.initial_balance

    @staticmethod
    def _trade_pnl_usd(trade: Trade) -> float:
        lot_size = float(trade.metadata.get("lot_size", 0.01))
        commission = float(trade.metadata.get("commission", 0.0))
        point_value = dollars_per_lot_per_point(trade.symbol)
        if trade.exit_price is None:
            return 0.0
        if trade.direction.value == "LONG":
            price_delta = trade.exit_price - trade.entry_price
        else:
            price_delta = trade.entry_price - trade.exit_price
        return price_delta * lot_size * point_value - commission

    def on_trade_closed(self, trade: Trade):
        pnl_usd = self._trade_pnl_usd(trade)
        trade.pnl = pnl_usd
        trade.metadata["pnl_usd"] = round(pnl_usd, 2)
        risk = abs(trade.entry_price - trade.stop_loss)
        if risk > 0 and trade.exit_price is not None:
            if trade.direction.value == "LONG":
                raw = trade.exit_price - trade.entry_price
            else:
                raw = trade.entry_price - trade.exit_price
            trade.risk_reward_achieved = round(raw / risk, 2)
        self.trades.append(trade)
        self.balance += pnl_usd

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
