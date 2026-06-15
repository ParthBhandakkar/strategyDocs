#!/usr/bin/env python3
"""Run a backtest from the CLI and persist results to JSON."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "documents"))

from backtester.connectors import get_data_client
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.strategies.registry import get_strategy

RESULTS_DIR = ROOT / "documents" / "backtester" / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a strategy backtest")
    parser.add_argument("strategy_id", help="Strategy id, e.g. s052_session_dol_fib")
    parser.add_argument("--symbol", default="MNQ", help="Trading symbol")
    parser.add_argument("--start", default="2024-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="2024-03-31", help="End date YYYY-MM-DD")
    parser.add_argument("--balance", type=float, default=10000.0)
    parser.add_argument("--risk", type=float, default=0.01, help="Risk per trade fraction")
    parser.add_argument(
        "--data-source",
        choices=["local", "mt5", "synthetic"],
        default=None,
        help="Override BACKTEST_DATA_SOURCE",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path (default: results/<strategy_id>.json)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    strat_cls = get_strategy(args.strategy_id)
    if not strat_cls:
        print(f"Strategy not found: {args.strategy_id}", file=sys.stderr)
        return 1

    start_dt = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)

    config = BacktestConfig(
        strategy_id=args.strategy_id,
        symbol=args.symbol,
        start_date=start_dt,
        end_date=end_dt,
        initial_balance=args.balance,
        risk_per_trade=args.risk,
    )

    client = get_data_client(args.data_source)
    try:
        engine = BacktestEngine(config, strat_cls(), client)
        result = engine.run()
    finally:
        client.close()

    output_path = Path(args.output) if args.output else RESULTS_DIR / f"{args.strategy_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = result.to_dict()
    payload["run_metadata"] = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "data_source": args.data_source or "auto",
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\nSaved results -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
