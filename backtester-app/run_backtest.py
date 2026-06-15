#!/usr/bin/env python3
"""
Run a strategy backtest and save JSON results.

Usage:
  PYTHONPATH=backtester-app/documents python backtester-app/run_backtest.py s054_range_sweep_mss
  PYTHONPATH=backtester-app/documents python backtester-app/run_backtest.py s044_lazy_liquidity_orb --symbol GBPUSD
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure backtester package is importable
DOCS_ROOT = Path(__file__).resolve().parent / "documents"
if str(DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCS_ROOT))

from backtester.connectors import get_data_client
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.strategies.registry import get_strategy

RESULTS_DIR = DOCS_ROOT / "backtester" / "results"

DEFAULT_SYMBOLS = {
    "s054_range_sweep_mss": "US100",
    "s003_liquidity_sweep_1m": "US100",
    "s044_lazy_liquidity_orb": "GBPUSD",
    "s012_8am_candle": "US100",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a strategy backtest")
    parser.add_argument("strategy_id", help="Strategy id, e.g. s054_range_sweep_mss")
    parser.add_argument("--symbol", help="Trading symbol (default per strategy)")
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Lookback days from today (default: 90)",
    )
    parser.add_argument(
        "--data-source",
        choices=["local", "mt5", "synthetic"],
        help="Override BACKTEST_DATA_SOURCE",
    )
    parser.add_argument(
        "--initial-balance",
        type=float,
        default=10_000.0,
    )
    parser.add_argument(
        "--risk-per-trade",
        type=float,
        default=0.01,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    StratClass = get_strategy(args.strategy_id)
    if not StratClass:
        print(f"Unknown strategy: {args.strategy_id}", file=sys.stderr)
        return 1

    symbol = args.symbol or DEFAULT_SYMBOLS.get(args.strategy_id, "US100")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)

    config = BacktestConfig(
        strategy_id=args.strategy_id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=args.initial_balance,
        risk_per_trade=args.risk_per_trade,
    )

    client = get_data_client(args.data_source)
    strategy = StratClass()
    engine = BacktestEngine(config, strategy, client)

    try:
        result = engine.run()
    finally:
        client.close()

    payload = result.to_dict()
    payload["meta"] = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "data_source": args.data_source or os.getenv("BACKTEST_DATA_SOURCE", "auto"),
        "canonical_module": _canonical_module(args.strategy_id),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{args.strategy_id}.json"
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    print(f"Results saved to {out_path}")
    return 0


def _canonical_module(strategy_id: str) -> str | None:
    """Best-effort map strategy id prefix to canonical module name."""
    try:
        video_num = int(strategy_id.split("_")[0][1:])
    except (IndexError, ValueError):
        return None
    mapping = {
        1: "vp_orderflow_absorption",
        4: "gold_london_vp_failed_auction",
        5: "multi_vp_ict",
        6: "htf_fvg_inversion",
        8: "vp_failed_auction_generic",
        13: "htf_trend_smt_cisd",
        17: "hourly_po3_fib",
        28: "ifvg_inversion_ladder",
        29: "tbv_absorption",
        31: "po3_10am_4h",
        39: "daily_bias_judas",
        42: "one_candle_8am",
        44: "london_orb",
        52: "session_dol_fib",
        54: "range_sweep_mss",
        56: "gold_judas_8pm",
        62: "continuation_purge",
        65: "us30_judas",
        69: "mmxm",
        77: "4h_swing_liquidity",
        78: "forex_session_judas",
        81: "osok_1h_po3",
    }
    return mapping.get(video_num)


if __name__ == "__main__":
    raise SystemExit(main())
