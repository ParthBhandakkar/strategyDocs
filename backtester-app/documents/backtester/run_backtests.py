#!/usr/bin/env python3
"""
Run backtests for all fully-coded strategies on every local Exness symbol.
Updates each strategy file header with per-symbol BACKTEST RESULTS.
"""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
sys.path.insert(0, str(DOCUMENTS_ROOT))

load_dotenv(BACKTESTER_ROOT / ".env")

from backtester.connectors import get_data_client
from backtester.connectors.local_history import LocalHistoryClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.strategies.registry import get_strategy, load_all_strategies

CODED_STRATEGIES = [
    "s003_liquidity_sweep_1m",
    "s004_volume_profile_auction",
    "s006_fractal_inversion_orderflow",
    "s012_8am_candle",
    "s013_800am_candle",
    "s026_inverse_fvg_scalp",
    "s027_po3_silver_bullet",
    "s038_4h_smt_divergence",
    "s044_lazy_liquidity_orb",
]

# s038 is XAU/XAG correlated — only meaningful on gold primary
SINGLE_SYMBOL_STRATEGIES = {
    "s038_4h_smt_divergence": ["XAUUSD"],
}

START = datetime(2024, 1, 1, tzinfo=timezone.utc)
END = datetime(2024, 6, 30, 23, 59, tzinfo=timezone.utc)


def format_line(symbol: str, result=None, error: str | None = None) -> str:
    if error:
        return f"  {symbol}: ERROR: {error}"
    return (
        f"  {symbol}: Trades: {result.total_trades} | Win rate: {result.win_rate}% | "
        f"PF: {result.profit_factor} | PnL: ${result.total_pnl:.2f} | "
        f"Max DD: {result.max_drawdown_pct}% | Avg R:R: {result.avg_rr}"
    )


def format_results_block(lines: list[str]) -> str:
    header = (
        f"BACKTEST RESULTS (local Exness CSV, {START.date()} to {END.date()}, all pairs):"
    )
    return header + "\n" + "\n".join(lines)


def patch_strategy_header(strategy_id: str, results_text: str) -> None:
    strat_class = get_strategy(strategy_id)
    if not strat_class:
        return
    module = sys.modules.get(strat_class.__module__)
    if not module or not hasattr(module, "__file__"):
        return
    path = Path(module.__file__)
    content = path.read_text(encoding="utf-8")
    marker = "BACKTEST RESULTS (local Exness CSV,"
    if marker in content:
        start = content.index(marker)
        end = content.find("\n\"\"\"", start)
        if end == -1:
            end = content.find('"""', start)
        if end != -1:
            content = content[:start] + results_text + content[end:]
    path.write_text(content, encoding="utf-8")


def run_one(strategy_id: str, symbol: str, client) -> dict:
    strat_class = get_strategy(strategy_id)
    if not strat_class:
        return {"error": "strategy not found"}

    config = BacktestConfig(
        strategy_id=strategy_id,
        symbol=symbol,
        start_date=START,
        end_date=END,
        initial_balance=10000.0,
        risk_per_trade=0.01,
    )
    try:
        with redirect_stdout(io.StringIO()):
            engine = BacktestEngine(config, strat_class(), client)
            result = engine.run()
        return {"result": result, "error": None}
    except Exception as exc:
        return {"result": None, "error": str(exc)}


def main():
    os.environ.setdefault("DATA_SOURCE", "local")
    load_all_strategies()

    client = get_data_client()
    if not isinstance(client, LocalHistoryClient):
        print("WARNING: expected local data client")
    symbols = client.get_symbols()
    print(f"Data source: local ({len(symbols)} symbols)")
    print(f"Data path: {os.getenv('LOCAL_HISTORY_PATH', 'default')}")
    print(f"Period: {START.date()} -> {END.date()}\n")

    for sid in CODED_STRATEGIES:
        run_symbols = SINGLE_SYMBOL_STRATEGIES.get(sid, symbols)
        lines: list[str] = []
        print(f"\n>>> {sid} ({len(run_symbols)} symbols)")

        for symbol in run_symbols:
            print(f"  {symbol}...", end=" ", flush=True)
            out = run_one(sid, symbol, client)
            if hasattr(client, "clear_cache"):
                client.clear_cache()
            if out.get("error"):
                lines.append(format_line(symbol, error=out["error"]))
                print("ERR")
            else:
                lines.append(format_line(symbol, result=out["result"]))
                print(f"{out['result'].total_trades} trades")

        patch_strategy_header(sid, format_results_block(lines))

    client.close()
    print("\nDone. Strategy headers updated.")


if __name__ == "__main__":
    main()
