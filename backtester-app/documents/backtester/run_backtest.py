#!/usr/bin/env python3
"""
Run a strategy backtest and persist results to backtest_results/.
Uses local Exness history by default (LOCAL_HISTORY_PATH).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

load_dotenv(BACKTESTER_ROOT / ".env")

from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.connectors import default_history_path, get_data_client
from backtester.strategies.registry import get_strategy

RESULTS_DIR = BACKTESTER_ROOT / "backtest_results"


def save_result(result, strategy_id: str, client) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = f"{strategy_id}_{int(datetime.now(timezone.utc).timestamp())}"
    out_path = RESULTS_DIR / f"{run_id}.json"
    payload = result.to_dict()
    payload["run_id"] = run_id
    payload["saved_at"] = datetime.now(timezone.utc).isoformat()
    health = client.health_check()
    payload["data_source"] = health.get("source", "unknown")
    if health.get("path"):
        payload["history_path"] = health["path"]
    elif health.get("source") == "local_history":
        payload["history_path"] = default_history_path()
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Run a backtest and save results.")
    parser.add_argument("strategy_id", help="Strategy registry id, e.g. s052_session_dol_fib")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2025-03-01")
    parser.add_argument("--balance", type=float, default=10000.0)
    parser.add_argument("--risk", type=float, default=0.01)
    parser.add_argument(
        "--data-source",
        choices=["local", "mt5", "synthetic"],
        default=None,
        help="Data source (default: local Exness history)",
    )
    parser.add_argument(
        "--history-path",
        default=None,
        help="Override LOCAL_HISTORY_PATH for this run",
    )
    parser.add_argument("--seed", type=int, default=42, help="Synthetic data seed")
    args = parser.parse_args()

    strat_cls = get_strategy(args.strategy_id)
    if not strat_cls:
        print(f"Strategy not found: {args.strategy_id}")
        sys.exit(1)

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

    client = get_data_client(
        source=args.data_source,
        history_root=args.history_path,
        synthetic_seed=args.seed,
    )
    health = client.health_check()
    print(f"Data source: {health}")

    engine = BacktestEngine(config, strat_cls(), client)
    result = engine.run()
    out_path = save_result(result, args.strategy_id, client)
    client.close()

    print(f"\nResults saved to {out_path}")
    print(f"Total trades: {result.total_trades}")
    print(f"Win rate: {result.win_rate}%")
    print(f"Total PnL: ${result.total_pnl:.2f}")


if __name__ == "__main__":
    main()
