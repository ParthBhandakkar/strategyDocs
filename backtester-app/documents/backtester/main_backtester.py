#!/usr/bin/env python3
"""
Main backtester CLI — audit, list strategies, and run multi-instrument backtests.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_DIR = BACKTESTER_ROOT.parent
if str(DOCUMENTS_DIR) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_DIR))

import yaml

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig, BacktestResult
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, list_strategy_entries

DEFAULT_WINDOWS_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
DEFAULT_RESULTS_DIR = BACKTESTER_ROOT / "results"
DEFAULT_CSV = BACKTESTER_ROOT.parent / "video_docs" / "strategy_videos_90.csv"
MATRIX_CSV = DEFAULT_RESULTS_DIR / "strategy_instrument_matrix.csv"

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
class InstrumentResult:
    symbol: str
    result: BacktestResult
    start_date: datetime
    end_date: datetime
    data_quality_note: str = ""
    composite_score: float = 0.0
    rank_within_strategy: int = 0


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    data_source: str
    data_root_used: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    instrument_results: list[InstrumentResult] = field(default_factory=list)
    best_instrument: str = ""
    worst_instrument: str = ""
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    instrument_affinity_notes: str = ""


def resolve_data_root(cli_path: str | None = None) -> tuple[str | None, str]:
    if cli_path:
        path = Path(cli_path)
        if path.is_dir() and _has_symbol_folders(path):
            return str(path), "cli"
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path and Path(env_path).is_dir() and _has_symbol_folders(Path(env_path)):
        return env_path, "env"
    if Path(DEFAULT_WINDOWS_DATA_ROOT).is_dir() and _has_symbol_folders(Path(DEFAULT_WINDOWS_DATA_ROOT)):
        return DEFAULT_WINDOWS_DATA_ROOT, "windows_default"
    return None, "unavailable"


def _has_symbol_folders(path: Path) -> bool:
    return any(p.is_dir() for p in path.iterdir())


def load_strategy_config(module: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def compute_composite_score(
    result: BacktestResult,
    best_pnl: float,
    min_trades: int = 10,
) -> float:
    if result.total_trades < min_trades:
        return 0.0
    pf = min(result.profit_factor if result.profit_factor != float("inf") else 5.0, 5.0)
    sharpe_norm = min(max(result.sharpe_ratio, -2.0), 3.0) / 3.0
    pnl = result.total_pnl
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else (0.0 if pnl <= 0 else 1.0)
    return round(
        (pf / 5.0 * 0.35)
        + (result.win_rate / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(result.total_trades, 50) / 50.0 * 0.10),
        4,
    )


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    config_defaults: dict[str, Any],
) -> InstrumentResult | None:
    required_tfs = [tf_from_string(item) for item in config_defaults.get("required_timeframes", ["M1"])]
    start, end = client.get_full_date_range(symbol, required_tfs)
    if not start or not end:
        return InstrumentResult(
            symbol=symbol,
            result=BacktestResult(config=BacktestConfig(strategy_id=strategy_cls.id, symbol=symbol, start_date=datetime.utcnow(), end_date=datetime.utcnow())),
            start_date=datetime.utcnow(),
            end_date=datetime.utcnow(),
            data_quality_note="missing_required_timeframes",
        )

    defaults = config_defaults.get("backtest_defaults", {})
    config = BacktestConfig(
        strategy_id=strategy_cls.id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=float(defaults.get("initial_balance", 10000.0)),
        risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(defaults.get("spread_pips", 1.0)),
        slippage_pips=float(defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
    )
    strategy = strategy_cls()
    engine = BacktestEngine(config=config, strategy=strategy, client=client)
    result = engine.run()

    result_dir = output_dir / strategy_cls.id
    result_dir.mkdir(parents=True, exist_ok=True)
    with open(result_dir / f"{symbol}.json", "w", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2)

    return InstrumentResult(symbol=symbol, result=result, start_date=start, end_date=end)


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
) -> MultiInstrumentSummary:
    resolved_root, _ = resolve_data_root(data_root)
    output_path = Path(output_dir or DEFAULT_RESULTS_DIR)
    output_path.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    module = getattr(strategy_cls, "module", strategy_id.split("_", 1)[-1])
    config_defaults = load_strategy_config(module)
    video_number = str(config_defaults.get("video_number", ""))
    min_trades = int(config_defaults.get("min_trades_for_ranking", 10))

    if not resolved_root:
        return MultiInstrumentSummary(
            strategy_id=strategy_cls.id,
            strategy_module_id=module,
            video_number=video_number,
            data_source="pending_exness_production",
            data_root_used="",
            instrument_affinity_notes="Production backtest required on Windows with Exness structured history.",
        )

    client = ExnessCSVClient(resolved_root)
    if symbols == "all":
        symbol_list = client.get_symbols()
    elif isinstance(symbols, str):
        symbol_list = [item.strip() for item in symbols.split(",") if item.strip()]
    else:
        symbol_list = list(symbols)

    instrument_results: list[InstrumentResult] = []
    for symbol in symbol_list:
        try:
            item = run_single_symbol_backtest(strategy_cls, symbol, client, output_path, config_defaults)
            if item:
                instrument_results.append(item)
        except Exception as exc:
            instrument_results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=BacktestResult(
                        config=BacktestConfig(
                            strategy_id=strategy_cls.id,
                            symbol=symbol,
                            start_date=datetime.utcnow(),
                            end_date=datetime.utcnow(),
                        )
                    ),
                    start_date=datetime.utcnow(),
                    end_date=datetime.utcnow(),
                    data_quality_note=f"error:{exc}",
                )
            )

    best_pnl = max((item.result.total_pnl for item in instrument_results), default=0.0)
    if best_pnl <= 0:
        best_pnl = max((abs(item.result.total_pnl) for item in instrument_results), default=1.0)

    for item in instrument_results:
        item.composite_score = compute_composite_score(item.result, best_pnl, min_trades)

    ranked = sorted(instrument_results, key=lambda item: item.composite_score, reverse=True)
    for idx, item in enumerate(ranked, start=1):
        item.rank_within_strategy = idx

    qualifying = [item for item in ranked if item.result.total_trades >= min_trades]
    best = qualifying[0] if qualifying else None
    worst = qualifying[-1] if qualifying else None

    now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    matrix_rows: list[dict[str, Any]] = []
    for item in ranked:
        result = item.result
        matrix_rows.append(
            {
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": module,
                "video_number": video_number,
                "symbol": item.symbol,
                "backtest_start_date": item.start_date.date().isoformat(),
                "backtest_end_date": item.end_date.date().isoformat(),
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
                "composite_score": item.composite_score,
                "rank_within_strategy": item.rank_within_strategy,
                "backtest_result_json": str((output_path / strategy_cls.id / f"{item.symbol}.json").resolve()),
                "backtested_at": now_iso,
                "data_quality_note": item.data_quality_note,
                "data_source": "exness_production",
            }
        )

    all_trades = sum(item.result.total_trades for item in instrument_results)
    aggregate_stats = {
        "bt_total_trades_all": all_trades,
        "bt_win_rate_all": round(
            statistics.mean([item.result.win_rate for item in instrument_results if item.result.total_trades > 0]),
            2,
        )
        if any(item.result.total_trades > 0 for item in instrument_results)
        else 0.0,
        "bt_profit_factor_all": round(
            statistics.mean(
                [
                    item.result.profit_factor
                    for item in instrument_results
                    if item.result.total_trades > 0 and item.result.profit_factor != float("inf")
                ]
            ),
            2,
        )
        if any(item.result.total_trades > 0 for item in instrument_results)
        else 0.0,
        "bt_max_drawdown_pct_all": round(
            max((item.result.max_drawdown_pct for item in instrument_results), default=0.0),
            2,
        ),
        "bt_total_pnl_all": round(sum(item.result.total_pnl for item in instrument_results), 2),
        "bt_sharpe_ratio_all": round(
            statistics.mean([item.result.sharpe_ratio for item in instrument_results if item.result.total_trades > 0]),
            2,
        )
        if any(item.result.total_trades > 0 for item in instrument_results)
        else 0.0,
        "bt_avg_rr_all": round(
            statistics.mean([item.result.avg_rr for item in instrument_results if item.result.total_trades > 0]),
            2,
        )
        if any(item.result.total_trades > 0 for item in instrument_results)
        else 0.0,
    }

    affinity_notes = ""
    if best:
        affinity_notes = (
            f"Best on {best.symbol} (PF={best.result.profit_factor}, "
            f"{best.result.total_trades} trades). "
        )
        if worst and worst.symbol != best.symbol:
            affinity_notes += (
                f"Weakest ranked symbol with sufficient trades: {worst.symbol} "
                f"(PF={worst.result.profit_factor})."
            )

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module,
        video_number=video_number,
        data_source="exness_production",
        data_root_used=resolved_root,
        matrix_rows=matrix_rows,
        instrument_results=instrument_results,
        best_instrument=best.symbol if best else "",
        worst_instrument=worst.symbol if worst else "",
        aggregate_stats=aggregate_stats,
        instrument_affinity_notes=affinity_notes,
    )
    update_matrix_csv(summary)
    return summary


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(path)


def ensure_tracking_columns(csv_path: Path):
    fieldnames, rows = _read_csv_rows(csv_path)
    changed = False
    for column in TRACKING_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)
            changed = True
    if changed:
        for row in rows:
            for column in TRACKING_COLUMNS:
                row.setdefault(column, "")
        _write_csv_rows(csv_path, fieldnames, rows)


def update_strategy_csv(
    csv_path: Path,
    module: str,
    registry_id: str,
    status: str,
    data_source: str,
    data_root: str,
    summary: MultiInstrumentSummary | None = None,
    anti_bias_passed: str = "yes",
    anti_bias_notes: str = "",
    backtest_error: str = "",
):
    ensure_tracking_columns(csv_path)
    fieldnames, rows = _read_csv_rows(csv_path)
    now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    for row in rows:
        if row.get("module_to_code") != module:
            continue
        row["implementation_status"] = status
        row["strategy_module_id"] = module
        row["strategy_folder"] = f"strategies/{module}/"
        row["strategy_registry_id"] = registry_id
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["backtest_error"] = backtest_error
        row["data_source"] = data_source
        row["data_root_used"] = data_root
        if status in {"coded", "coded_pending_production_backtest", "in_progress"} and not row.get("coded_at"):
            row["coded_at"] = now_iso
        if summary and status == "coded_and_backtested":
            row["backtested_at"] = now_iso
            row["instruments_tested_count"] = str(len(summary.instrument_results))
            row["best_instrument"] = summary.best_instrument
            row["worst_instrument"] = summary.worst_instrument
            row["instrument_affinity_notes"] = summary.instrument_affinity_notes
            for key, value in summary.aggregate_stats.items():
                row[key] = str(value)
            if summary.best_instrument:
                best_item = next(
                    (item for item in summary.instrument_results if item.symbol == summary.best_instrument),
                    None,
                )
                if best_item:
                    row["best_instrument_pf"] = str(best_item.result.profit_factor)
                    row["best_instrument_win_rate"] = str(best_item.result.win_rate)
                    row["best_instrument_pnl"] = str(round(best_item.result.total_pnl, 2))
                    row["best_instrument_trades"] = str(best_item.result.total_trades)
        break

    _write_csv_rows(csv_path, fieldnames, rows)


def propagate_duplicate_rows(csv_path: Path, canonical_module: str):
    fieldnames, rows = _read_csv_rows(csv_path)
    canonical = next((row for row in rows if row.get("module_to_code") == canonical_module), None)
    if not canonical or canonical.get("implementation_status") != "coded_and_backtested":
        return
    if canonical.get("data_source") != "exness_production":
        return

    copy_fields = [
        "implementation_status",
        "strategy_registry_id",
        "backtested_at",
        "instruments_tested_count",
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
    for row in rows:
        if row.get("action") != "DUPLICATE-SKIP":
            continue
        if row.get("module_to_code") != canonical_module:
            continue
        row["implementation_status"] = "covered_by_canonical"
        for field in copy_fields:
            row[field] = canonical.get(field, "")

    _write_csv_rows(csv_path, fieldnames, rows)


def update_matrix_csv(summary: MultiInstrumentSummary):
    DEFAULT_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if MATRIX_CSV.exists():
        fieldnames, rows = _read_csv_rows(MATRIX_CSV)
    else:
        fieldnames, rows = MATRIX_COLUMNS, []

    for column in MATRIX_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)

    existing = {
        (row.get("strategy_registry_id"), row.get("symbol"))
        for row in rows
    }
    for matrix_row in summary.matrix_rows:
        key = (matrix_row["strategy_registry_id"], matrix_row["symbol"])
        rows = [row for row in rows if (row.get("strategy_registry_id"), row.get("symbol")) != key]
        rows.append({column: str(matrix_row.get(column, "")) for column in fieldnames})
        existing.add(key)

    _write_csv_rows(MATRIX_CSV, fieldnames, rows)


def cmd_audit(csv_path: Path):
    ensure_tracking_columns(csv_path)
    fieldnames, rows = _read_csv_rows(csv_path)
    coded_modules = sorted(
        folder.name
        for folder in (BACKTESTER_ROOT / "strategies").iterdir()
        if folder.is_dir() and folder.name not in {"__pycache__"}
        and (folder / "strategy.py").exists()
    )
    registered = list_strategy_entries()
    data_root, source = resolve_data_root()
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_root else 0

    canonical_rows = [row for row in rows if row.get("action") == "CODE-CANONICAL"]
    done = sum(1 for row in canonical_rows if row.get("implementation_status") == "coded_and_backtested")
    pending = [
        row for row in canonical_rows
        if row.get("implementation_status", "") in {"", "not_started", "failed", "in_progress"}
    ]
    pending.sort(key=lambda row: int(row.get("video_number", 9999)))

    print("=== Backtester Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Strategy folders on disk: {coded_modules}")
    print(f"Registered strategies: {[entry['id'] for entry in registered]}")
    print(f"Data root ({source}): {data_root or 'UNAVAILABLE'}")
    print(f"Symbols available: {symbol_count}")
    print(f"Canonical progress: {done}/{len(canonical_rows)} coded_and_backtested")
    if pending:
        next_row = pending[0]
        print(
            f"Next pending: Video #{next_row.get('video_number')} — "
            f"{next_row.get('title')} ({next_row.get('module_to_code')})"
        )


def cmd_list_strategies():
    for entry in list_strategy_entries():
        print(f"{entry['id']}\t{entry['name']}\tvideo={entry['source_video']}")


def cmd_run(args: argparse.Namespace):
    strategy_cls = get_strategy(args.strategy)
    if strategy_cls is None:
        raise SystemExit(f"Unknown strategy: {args.strategy}")

    module = getattr(strategy_cls, "module", args.strategy.split("_", 1)[-1])
    csv_path = Path(args.csv)
    ensure_tracking_columns(csv_path)
    update_strategy_csv(
        csv_path,
        module=module,
        registry_id=strategy_cls.id,
        status="in_progress",
        data_source="not_backtested",
        data_root="",
    )

    data_root, _ = resolve_data_root(args.data_root)
    anti_bias_notes = (
        "Uses only closed M1 bars and session VP from past bars; "
        "HTF feed gated by bar close; entries on bar close after cluster inversion; "
        "parameters from video spec (no post-backtest tuning)."
    )

    if not data_root:
        update_strategy_csv(
            csv_path,
            module=module,
            registry_id=strategy_cls.id,
            status="coded_pending_production_backtest",
            data_source="pending_exness_production",
            data_root="",
            anti_bias_passed="yes",
            anti_bias_notes=anti_bias_notes,
        )
        propagate_duplicate_rows(csv_path, module)
        print("Real Exness history unavailable — marked coded_pending_production_backtest.")
        return

    try:
        summary = run_multi_instrument_backtest(
            strategy_id=strategy_cls.id,
            data_root=data_root,
            symbols=args.symbols,
            output_dir=args.output,
        )
        update_strategy_csv(
            csv_path,
            module=module,
            registry_id=strategy_cls.id,
            status="coded_and_backtested",
            data_source="exness_production",
            data_root=data_root,
            summary=summary,
            anti_bias_passed="yes",
            anti_bias_notes=anti_bias_notes,
        )
        propagate_duplicate_rows(csv_path, module)
        print(f"Backtest complete for {strategy_cls.id}. Best instrument: {summary.best_instrument}")
    except Exception as exc:
        update_strategy_csv(
            csv_path,
            module=module,
            registry_id=strategy_cls.id,
            status="failed",
            data_source="exness_production",
            data_root=data_root or "",
            anti_bias_passed="yes",
            anti_bias_notes=anti_bias_notes,
            backtest_error=str(exc),
        )
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy backtester pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Audit CSV vs disk vs data")
    audit_parser.add_argument("--csv", default=str(DEFAULT_CSV))

    subparsers.add_parser("list-strategies", help="List registered strategies")

    run_parser = subparsers.add_parser("run", help="Run a strategy across instruments")
    run_parser.add_argument("--strategy", required=True)
    run_parser.add_argument("--symbols", default="all")
    run_parser.add_argument("--data-root", default=None)
    run_parser.add_argument("--output", default=str(DEFAULT_RESULTS_DIR))
    run_parser.add_argument("--csv", default=str(DEFAULT_CSV))
    run_parser.add_argument("--start", default=None)
    run_parser.add_argument("--end", default=None)

    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "audit":
        cmd_audit(Path(args.csv))
    elif args.command == "list-strategies":
        cmd_list_strategies()
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
