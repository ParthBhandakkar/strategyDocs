#!/usr/bin/env python3
"""
Run a backtest for a registered strategy and save JSON results.

Usage:
  PYTHONPATH=backtester-app/documents python backtester-app/run_backtest.py s054_range_sweep_mss
  BACKTEST_DATA_SOURCE=synthetic PYTHONPATH=... python backtester-app/run_backtest.py s044_lazy_liquidity_orb --symbol GBPUSD
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DOCS = Path(__file__).resolve().parent / "documents"
sys.path.insert(0, str(DOCS))

from backtester.connectors import get_data_client
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.strategies.registry import get_strategy

RESULTS_DIR = DOCS / "backtester" / "results"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run strategy backtest")
    parser.add_argument("strategy_id", help="Registered strategy id, e.g. s054_range_sweep_mss")
    parser.add_argument("--symbol", default="EURUSD", help="Trading symbol")
    parser.add_argument("--days", type=int, default=90, help="Lookback days from today")
    parser.add_argument("--balance", type=float, default=10000.0)
    parser.add_argument("--risk", type=float, default=0.01, help="Risk per trade (fraction)")
    args = parser.parse_args()

    StratClass = get_strategy(args.strategy_id)
    if not StratClass:
        print(f"Strategy not found: {args.strategy_id}", file=sys.stderr)
        return 1

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)

    config = BacktestConfig(
        strategy_id=args.strategy_id,
        symbol=args.symbol,
        start_date=start,
        end_date=end,
        initial_balance=args.balance,
        risk_per_trade=args.risk,
    )

    client = get_data_client()
    health = client.health_check()
    print(f"Data source: {health}")

    strategy = StratClass()
    engine = BacktestEngine(config, strategy, client)

    try:
        result = engine.run()
    finally:
        client.close()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{args.strategy_id}_{args.symbol}_{end.strftime('%Y%m%d')}.json"
    payload = result.to_dict()
    payload["strategy_id"] = args.strategy_id
    payload["data_source"] = health

    with out_path.open("w") as f:
        json.dump(payload, f, indent=2, default=str)

    stats = payload.get("stats", {})
    print(f"\nSaved: {out_path}")
    print(
        f"Trades: {stats.get('total_trades', 0)} | "
        f"Win rate: {stats.get('win_rate', 0)}% | "
        f"PnL: {stats.get('total_pnl', 0)} | "
        f"PF: {stats.get('profit_factor', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
