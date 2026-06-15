#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, and multi-instrument run.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from backtester.connectors import ExnessCSVClient, default_data_root, get_data_client
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_module_name, get_strategy, load_all_strategies

BACKTESTER_ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = BACKTESTER_ROOT.parent / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
MATRIX_CSV = "strategy_instrument_matrix.csv"

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
]


@dataclass
class InstrumentResult:
    symbol: str
    result: Any
    start_date: str
    end_date: str
    data_quality_note: str = ""
    composite_score: float = 0.0
    rank_within_strategy: int = 0


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    module_id: str
    video_number: int
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    instrument_results: list[InstrumentResult] = field(default_factory=list)
    best_instrument: str = ""
    worst_instrument: str = ""
    aggregate_stats: dict[str, Any] = field(default_factory=dict)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _parse_symbols_arg(symbols: str, client: ExnessCSVClient) -> list[str]:
    if symbols.lower() == "all":
        return client.get_symbols()
    return [s.strip().upper() for s in symbols.split(",") if s.strip()]


def _compute_composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0))
    if trades < min_trades:
        return 0.0

    pf = min(float(row.get("bt_profit_factor", 0)), 5.0)
    win_rate = float(row.get("bt_win_rate", 0))
    sharpe = float(row.get("bt_sharpe_ratio", 0))
    pnl = float(row.get("bt_total_pnl", 0))

    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0

    return round(
        (pf / 5.0 * 0.35)
        + (win_rate / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10),
        4,
    )


def _result_row(
    strategy_id: str,
    module_id: str,
    video_number: int,
    symbol: str,
    result,
    start,
    end,
    output_dir: Path,
    data_quality_note: str = "",
) -> dict[str, Any]:
    json_path = output_dir / strategy_id / f"{symbol}.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = result.to_dict()
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    return {
        "strategy_registry_id": strategy_id,
        "strategy_module_id": module_id,
        "video_number": video_number,
        "symbol": symbol,
        "backtest_start_date": start.isoformat() if start else "",
        "backtest_end_date": end.isoformat() if end else "",
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
        "backtest_result_json": str(json_path),
        "backtested_at": _utc_now_iso(),
        "data_quality_note": data_quality_note,
    }


def _update_matrix_csv(output_dir: Path, new_rows: list[dict[str, Any]]):
    matrix_path = output_dir / MATRIX_CSV
    existing: dict[tuple[str, str], dict[str, Any]] = {}

    if matrix_path.exists():
        with open(matrix_path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row

    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {col: str(row.get(col, "")) for col in MATRIX_COLUMNS}

    with open(matrix_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda r: (r["strategy_registry_id"], r["symbol"])):
            writer.writerow(row)


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    load_all_strategies()
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module_name = get_module_name(strategy_cls.id) or strategy_id
    config_data = _load_strategy_config(module_name)
    video_number = int(config_data.get("video_number", 0))
    defaults = config_data.get("backtest_defaults", {})
    required_tf_strings = config_data.get("required_timeframes", [])
    required_tfs = [tf_from_string(s) for s in required_tf_strings] if required_tf_strings else list(strategy_cls.timeframes)

    client = get_data_client(data_root or default_data_root())
    symbol_list = _parse_symbols_arg(symbols, client)
    out_path = Path(output_dir or DEFAULT_OUTPUT)
    out_path.mkdir(parents=True, exist_ok=True)

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        module_id=module_name,
        video_number=video_number,
        instruments_scanned=len(symbol_list),
    )

    matrix_rows: list[dict[str, Any]] = []

    for symbol in symbol_list:
        sym_start, sym_end, missing = client.get_full_date_range(symbol, required_tfs)
        if missing:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = f"missing timeframes: {', '.join(missing)}"
            continue

        use_start = start or sym_start
        use_end = end or sym_end
        if use_start is None or use_end is None:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = "no date range"
            continue

        strategy = strategy_cls()
        bt_config = BacktestConfig(
            strategy_id=strategy_cls.id,
            symbol=symbol,
            start_date=use_start,
            end_date=use_end,
            initial_balance=float(defaults.get("initial_balance", 10000.0)),
            risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
            spread_pips=float(defaults.get("spread_pips", 1.0)),
            slippage_pips=float(defaults.get("slippage_pips", 0.5)),
            commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
        )

        engine = BacktestEngine(bt_config, strategy, client)
        result = engine.run()
        row = _result_row(
            strategy_cls.id,
            module_name,
            video_number,
            symbol,
            result,
            use_start,
            use_end,
            out_path,
        )
        matrix_rows.append(row)
        summary.instrument_results.append(
            InstrumentResult(symbol=symbol, result=result, start_date=row["backtest_start_date"], end_date=row["backtest_end_date"])
        )
        summary.instruments_tested += 1

    best_pnl = max((float(r["bt_total_pnl"]) for r in matrix_rows), default=0.0)
    min_trades = int(config_data.get("min_trades_for_ranking", 10))

    for row in matrix_rows:
        row["composite_score"] = _compute_composite_score(row, best_pnl, min_trades)

    ranked = sorted(matrix_rows, key=lambda r: float(r["composite_score"]), reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = rank

    _update_matrix_csv(out_path, matrix_rows)
    summary.matrix_rows = matrix_rows

    eligible = [r for r in matrix_rows if int(r["bt_total_trades"]) >= min_trades]
    if eligible:
        best = max(eligible, key=lambda r: float(r["composite_score"]))
        worst = min(eligible, key=lambda r: float(r["composite_score"]))
        summary.best_instrument = best["symbol"]
        summary.worst_instrument = worst["symbol"]

    total_trades = sum(int(r["bt_total_trades"]) for r in matrix_rows)
    total_pnl = sum(float(r["bt_total_pnl"]) for r in matrix_rows)
    win_rates = [float(r["bt_win_rate"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]
    pfs = [float(r["bt_profit_factor"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]
    dds = [float(r["bt_max_drawdown_pct"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]
    sharpes = [float(r["bt_sharpe_ratio"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]
    rrs = [float(r["bt_avg_rr"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]

    summary.aggregate_stats = {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": round(sum(win_rates) / len(win_rates), 2) if win_rates else 0.0,
        "bt_profit_factor_all": round(sum(pfs) / len(pfs), 2) if pfs else 0.0,
        "bt_max_drawdown_pct_all": round(max(dds), 2) if dds else 0.0,
        "bt_total_pnl_all": round(total_pnl, 2),
        "bt_sharpe_ratio_all": round(sum(sharpes) / len(sharpes), 2) if sharpes else 0.0,
        "bt_avg_rr_all": round(sum(rrs) / len(rrs), 2) if rrs else 0.0,
    }

    return summary


def _read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=csv_path.parent, suffix=".csv.tmp")
    os.close(fd)
    try:
        with open(tmp_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, csv_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _ensure_tracking_columns(fieldnames: list[str]) -> list[str]:
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    fieldnames, rows = _read_csv_rows(csv_path)
    fieldnames = _ensure_tracking_columns(fieldnames)

    load_all_strategies()
    registered = {cls.id: get_module_name(cls.id) for cls in get_all_strategies()}
    strategy_dirs = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__"}
    }

    canonical = [r for r in rows if r.get("action") == "CODE-CANONICAL"]
    done = [r for r in canonical if r.get("implementation_status") == "coded_and_backtested"]
    pending = [r for r in canonical if r.get("implementation_status", "") in ("", "not_started", "failed", "in_progress")]

    print("=== Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Canonical modules: {len(canonical)}")
    print(f"Completed: {len(done)}")
    print(f"Pending: {len(pending)}")
    print(f"Registered strategies: {len(registered)}")
    for strat_id, module in sorted(registered.items()):
        print(f"  - {strat_id} ({module})")
    print(f"Strategy folders on disk: {sorted(strategy_dirs)}")
    print(f"main_backtester.py: {'yes' if (BACKTESTER_ROOT / 'main_backtester.py').exists() else 'no'}")
    print(f"exness_csv.py: {'yes' if (BACKTESTER_ROOT / 'connectors' / 'exness_csv.py').exists() else 'no'}")

    changed = False
    for row in rows:
        for col in TRACKING_COLUMNS:
            if col not in row:
                row[col] = ""
                changed = True

    if changed:
        _write_csv_atomic(csv_path, fieldnames, rows)
        print("Added missing tracking columns to CSV.")

    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    strategies = get_all_strategies()
    if not strategies:
        print("No strategies registered.")
        return 1
    for cls in sorted(strategies, key=lambda c: c.id):
        print(f"{cls.id}\t{cls.name}\tvideo={cls.source_video}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        summary = run_multi_instrument_backtest(
            strategy_id=args.strategy,
            data_root=args.data_root,
            symbols=args.symbols,
            output_dir=args.output,
        )
    except Exception as exc:
        print(f"Backtest failed: {exc}")
        return 1

    print("\n=== Multi-Instrument Summary ===")
    print(f"Strategy: {summary.strategy_id}")
    print(f"Scanned: {summary.instruments_scanned}")
    print(f"Tested:  {summary.instruments_tested}")
    print(f"Skipped: {summary.instruments_skipped}")
    for symbol, reason in summary.skip_reasons.items():
        print(f"  {symbol}: {reason}")
    print(f"Best: {summary.best_instrument}")
    print(f"Worst: {summary.worst_instrument}")
    print(f"Aggregate: {summary.aggregate_stats}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit_p.add_argument("--csv", default=str(DEFAULT_CSV))

    sub.add_parser("list-strategies", help="List registered strategies")

    run_p = sub.add_parser("run", help="Run multi-instrument backtest")
    run_p.add_argument("--strategy", required=True)
    run_p.add_argument("--symbols", default="all")
    run_p.add_argument("--data-root", default=None)
    run_p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_p.add_argument("--start", default=None)
    run_p.add_argument("--end", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "audit":
        return cmd_audit(args)
    if args.command == "list-strategies":
        return cmd_list_strategies(args)
    if args.command == "run":
        return cmd_run(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
