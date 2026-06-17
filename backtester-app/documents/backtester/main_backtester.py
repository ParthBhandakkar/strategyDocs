#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, run multi-instrument backtests.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure backtester package is importable
_DOCS_ROOT = Path(__file__).resolve().parent.parent
if str(_DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(_DOCS_ROOT))

import yaml

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig, BacktestResult
from backtester.core.timeframes import TF, tf_from_string
from backtester.core.engine import BacktestEngine
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies

logger = logging.getLogger(__name__)

DEFAULT_CSV = _DOCS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "results"
MATRIX_CSV = DEFAULT_OUTPUT / "strategy_instrument_matrix.csv"

TRACKING_COLUMNS = [
    "implementation_status",
    "strategy_module_id",
    "strategy_folder",
    "strategy_registry_id",
    "coded_at",
    "backtested_at",
    "instruments_tested_count",
    "anti_bias_review_passed",
    "anti_bias_notes",
    "backtest_error",
    "data_source",
    "data_root_used",
    "bt_total_trades_all",
    "bt_win_rate_all",
    "bt_profit_factor_all",
    "bt_max_drawdown_pct_all",
    "bt_total_pnl_all",
    "bt_sharpe_ratio_all",
    "bt_avg_rr_all",
    "best_instrument",
    "best_instrument_pf",
    "best_instrument_win_rate",
    "best_instrument_pnl",
    "best_instrument_trades",
    "worst_instrument",
    "instrument_affinity_notes",
]

MATRIX_COLUMNS = [
    "strategy_registry_id",
    "strategy_module_id",
    "video_number",
    "symbol",
    "backtest_start_date",
    "backtest_end_date",
    "bt_total_trades",
    "bt_winning_trades",
    "bt_losing_trades",
    "bt_win_rate",
    "bt_profit_factor",
    "bt_max_drawdown_pct",
    "bt_total_pnl",
    "bt_sharpe_ratio",
    "bt_avg_rr",
    "bt_avg_trade_duration_mins",
    "composite_score",
    "rank_within_strategy",
    "backtest_result_json",
    "backtested_at",
    "data_quality_note",
    "data_source",
]


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    best_instrument: str = ""
    worst_instrument: str = ""
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_path: str | None) -> tuple[str, bool]:
    """Return (path, is_real_production). is_real=False when path missing."""
    if cli_path:
        p = Path(cli_path)
        if p.is_dir() and _has_symbol_folders(p):
            return str(p), True
    env = os.environ.get("LOCAL_HISTORY_PATH", "")
    if env and Path(env).is_dir() and _has_symbol_folders(Path(env)):
        return env, True
    default = ExnessCSVClient.default_data_root()
    if Path(default).is_dir() and _has_symbol_folders(Path(default)):
        return default, True
    return default, False


def _has_symbol_folders(path: Path) -> bool:
    return any(p.is_dir() and not p.name.startswith(".") for p in path.iterdir())


def _load_strategy_config(module: str) -> dict[str, Any]:
    cfg_path = Path(__file__).parent / "strategies" / module / "config.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def _write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=csv_path.parent, suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, csv_path)
    except Exception:
        os.unlink(tmp)
        raise


def _composite_score(row: dict[str, Any], max_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0) or 0)
    if trades < min_trades:
        return -1.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0)
    wr = float(row.get("bt_win_rate", 0) or 0)
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / max_pnl) if max_pnl > 0 else 0.0
    return (
        (pf / 5.0 * 0.35)
        + (wr / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10)
    )


def _result_row(
    strategy_id: str,
    module: str,
    video_number: str,
    symbol: str,
    result: BacktestResult,
    start: datetime,
    end: datetime,
    data_source: str,
    json_path: str,
) -> dict[str, Any]:
    return {
        "strategy_registry_id": strategy_id,
        "strategy_module_id": module,
        "video_number": video_number,
        "symbol": symbol,
        "backtest_start_date": start.date().isoformat(),
        "backtest_end_date": end.date().isoformat(),
        "bt_total_trades": result.total_trades,
        "bt_winning_trades": result.winning_trades,
        "bt_losing_trades": result.losing_trades,
        "bt_win_rate": result.win_rate,
        "bt_profit_factor": result.profit_factor,
        "bt_max_drawdown_pct": result.max_drawdown_pct,
        "bt_total_pnl": round(result.total_pnl, 2),
        "bt_sharpe_ratio": result.sharpe_ratio,
        "bt_avg_rr": result.avg_rr,
        "bt_avg_trade_duration_mins": result.avg_trade_duration,
        "composite_score": 0.0,
        "rank_within_strategy": 0,
        "backtest_result_json": json_path,
        "backtested_at": _utc_now_iso(),
        "data_quality_note": "",
        "data_source": data_source,
    }


def _aggregate_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    total_trades = sum(int(r.get("bt_total_trades", 0) or 0) for r in rows)
    total_wins = sum(int(r.get("bt_winning_trades", 0) or 0) for r in rows)
    total_pnl = sum(float(r.get("bt_total_pnl", 0) or 0) for r in rows)
    pf_vals = [float(r["bt_profit_factor"]) for r in rows if r.get("bt_profit_factor") not in ("", None, "inf")]
    max_dd = max((float(r.get("bt_max_drawdown_pct", 0) or 0) for r in rows), default=0.0)
    sharpe_vals = [float(r.get("bt_sharpe_ratio", 0) or 0) for r in rows]
    rr_vals = [float(r.get("bt_avg_rr", 0) or 0) for r in rows if int(r.get("bt_total_trades", 0) or 0) > 0]
    return {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0,
        "bt_profit_factor_all": round(sum(pf_vals) / len(pf_vals), 2) if pf_vals else 0,
        "bt_max_drawdown_pct_all": round(max_dd, 2),
        "bt_total_pnl_all": round(total_pnl, 2),
        "bt_sharpe_ratio_all": round(sum(sharpe_vals) / len(sharpe_vals), 2) if sharpe_vals else 0,
        "bt_avg_rr_all": round(sum(rr_vals) / len(rr_vals), 2) if rr_vals else 0,
    }


def _update_matrix_csv(new_rows: list[dict[str, Any]]):
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if MATRIX_CSV.exists():
        with open(MATRIX_CSV, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row
    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {k: str(v) for k, v in row.items()}
    _write_csv_atomic(MATRIX_CSV, MATRIX_COLUMNS, list(existing.values()))


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    load_all_strategies()
    strategy_cls = get_strategy(strategy_id)
    if not strategy_cls:
        raise ValueError(f"Strategy not found: {strategy_id}")

    strategy = strategy_cls()
    module = strategy_id.split("_", 1)[-1] if "_" in strategy_id else strategy_id
    cfg = _load_strategy_config(module)
    defaults = cfg.get("backtest_defaults", {})
    video_number = str(cfg.get("video_number", strategy.source_video or ""))

    root_path, is_real = resolve_data_root(data_root)
    client = ExnessCSVClient(root_path)
    data_source = "exness_production" if is_real else "not_backtested"

    out = Path(output_dir or DEFAULT_OUTPUT)
    out.mkdir(parents=True, exist_ok=True)
    result_dir = out / strategy.id
    result_dir.mkdir(parents=True, exist_ok=True)

    if symbols == "all":
        symbol_list = client.get_symbols()
    elif isinstance(symbols, str):
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        symbol_list = list(symbols)

    summary = MultiInstrumentSummary(
        strategy_id=strategy.id,
        strategy_module_id=module,
        video_number=video_number,
        instruments_scanned=len(symbol_list),
        data_source=data_source if is_real else "pending_exness_production",
        data_root_used=root_path,
    )

    if not is_real:
        summary.instruments_skipped = len(symbol_list)
        for sym in symbol_list:
            summary.skip_reasons[sym] = "production data path unavailable"
        return summary

    required_tfs = [tf_from_string(t) for t in cfg.get("required_timeframes", [])]
    if not required_tfs:
        required_tfs = list(strategy.timeframes)

    matrix_rows: list[dict[str, Any]] = []

    for symbol in symbol_list:
        missing = [tf for tf in required_tfs if not client.has_timeframe(symbol, tf)]
        if missing:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = f"missing timeframes: {[tf.name for tf in missing]}"
            continue

        date_range = client.get_full_date_range(symbol, required_tfs)
        if not date_range:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = "no date range"
            continue

        sym_start, sym_end = date_range
        if start:
            sym_start = max(sym_start, start)
        if end:
            sym_end = min(sym_end, end)

        config = BacktestConfig(
            strategy_id=strategy.id,
            symbol=symbol,
            start_date=sym_start,
            end_date=sym_end,
            initial_balance=float(defaults.get("initial_balance", 10000.0)),
            risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
            spread_pips=float(defaults.get("spread_pips", 1.0)),
            slippage_pips=float(defaults.get("slippage_pips", 0.5)),
            commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
        )

        try:
            engine = BacktestEngine(config, strategy_cls(), client)
            result = engine.run()
        except Exception as exc:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = str(exc)
            logger.exception("Backtest failed for %s", symbol)
            continue

        json_path = str(result_dir / f"{symbol}.json")
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(result.to_dict(), fh, indent=2)

        row = _result_row(
            strategy.id, module, video_number, symbol, result,
            sym_start, sym_end, data_source, json_path,
        )
        matrix_rows.append(row)
        summary.instruments_tested += 1

    if matrix_rows:
        max_pnl = max(float(r["bt_total_pnl"]) for r in matrix_rows)
        min_trades = int(cfg.get("min_trades_for_ranking", 10))
        for row in matrix_rows:
            row["composite_score"] = round(_composite_score(row, max_pnl, min_trades), 4)
        ranked = sorted(matrix_rows, key=lambda r: r["composite_score"], reverse=True)
        for rank, row in enumerate(ranked, start=1):
            row["rank_within_strategy"] = rank

        eligible = [r for r in ranked if r["composite_score"] >= 0]
        if eligible:
            best = eligible[0]
            worst = eligible[-1]
            summary.best_instrument = best["symbol"]
            summary.worst_instrument = worst["symbol"]

        summary.matrix_rows = matrix_rows
        summary.aggregate_stats = _aggregate_stats(matrix_rows)
        _update_matrix_csv(matrix_rows)

    return summary


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    fieldnames, rows = _read_csv_rows(csv_path)
    load_all_strategies()
    coded_modules = {
        p.name
        for p in (Path(__file__).parent / "strategies").iterdir()
        if p.is_dir() and p.name not in ("__pycache__",)
    }
    coded_modules -= {"base", "registry"}

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")
    pending = [
        r for r in canonical
        if r.get("implementation_status", "") in ("", "not_started", "in_progress", "failed", "coded", "coded_pending_production_backtest")
    ]

    root, is_real = resolve_data_root(args.data_root)
    sym_count = len(ExnessCSVClient(root).get_symbols()) if is_real else 0

    print(f"Canonical modules: {len(canonical)} total, {done} coded_and_backtested")
    print(f"Strategy folders on disk: {sorted(coded_modules)}")
    print(f"Registered strategies: {[s().id for s in get_all_strategies()]}")
    print(f"Data root: {root} ({'available' if is_real else 'MISSING'}) — {sym_count} symbols")
    if pending:
        nxt = min(pending, key=lambda r: int(r.get("video_number", 999)))
        print(f"Next pending: Video #{nxt.get('video_number')} — {nxt.get('module_to_code')}")
    else:
        print("No pending canonical modules.")
    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    load_all_strategies()
    for cls in get_all_strategies():
        s = cls()
        print(f"{s.id:40s} {s.name}  TFs={[tf.name for tf in s.timeframes]}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    print(f"\nStrategy: {summary.strategy_id}")
    print(f"Scanned: {summary.instruments_scanned}, Tested: {summary.instruments_tested}, Skipped: {summary.instruments_skipped}")
    if summary.best_instrument:
        print(f"Best: {summary.best_instrument}, Worst: {summary.worst_instrument}")
    if summary.aggregate_stats:
        print(f"Aggregate: {summary.aggregate_stats}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit_p.add_argument("--csv", default=str(DEFAULT_CSV))
    audit_p.add_argument("--data-root", default=None)

    sub.add_parser("list-strategies", help="List registered strategies")

    run_p = sub.add_parser("run", help="Run multi-instrument backtest")
    run_p.add_argument("--strategy", required=True)
    run_p.add_argument("--symbols", default="all")
    run_p.add_argument("--data-root", default=None)
    run_p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_p.add_argument("--start", default=None)
    run_p.add_argument("--end", default=None)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.command == "audit":
        return cmd_audit(args)
    if args.command == "list-strategies":
        return cmd_list_strategies(args)
    if args.command == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
