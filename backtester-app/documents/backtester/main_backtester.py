#!/usr/bin/env python3
"""
Main backtester CLI — audit, list strategies, and run multi-instrument backtests.
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
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = ROOT.parent
if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_strategy, list_strategy_metadata, load_all_strategies

DEFAULT_WINDOWS_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = ROOT / "results"
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
class InstrumentResult:
    symbol: str
    result: Any
    composite_score: float = 0.0
    rank_within_strategy: int = 0
    data_quality_note: str = ""
    skipped: bool = False


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    module_id: str
    video_number: str
    best_instrument: str = ""
    worst_instrument: str = ""
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_data_root: str | None = None) -> tuple[str, bool]:
    if cli_data_root:
        path = Path(cli_data_root)
        if path.is_dir() and _has_symbol_data(path):
            return str(path), True
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_data(path):
            return str(path), True
    default_path = Path(DEFAULT_WINDOWS_DATA_ROOT)
    if default_path.is_dir() and _has_symbol_data(default_path):
        return str(default_path), True
    return str(default_path), False


def _has_symbol_data(path: Path) -> bool:
    for item in path.iterdir():
        if item.is_dir():
            for tf_dir in item.iterdir():
                if tf_dir.is_dir() and any(tf_dir.glob("*.csv")):
                    return True
    return False


def load_yaml_defaults(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for column in TRACKING_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)
    return fieldnames, rows


def write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8") as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        temp_name = tmp.name
    os.replace(temp_name, csv_path)


def ensure_matrix_csv():
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    if MATRIX_CSV.exists():
        return
    with MATRIX_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()


def audit_strategies(csv_path: Path) -> dict[str, Any]:
    fieldnames, rows = read_csv_rows(csv_path)
    load_all_strategies(force=True)
    coded_modules = {
        item["module"]
        for item in list_strategy_metadata()
    }
    canonical_rows = [
        row for row in rows
        if row.get("action") == "CODE-CANONICAL" and row.get("is_backtestable") == "yes"
    ]
    done = sum(1 for row in canonical_rows if row.get("implementation_status") == "coded_and_backtested")
    pending = [
        row for row in canonical_rows
        if row.get("implementation_status", "") in {"", "not_started", "failed", "in_progress"}
    ]
    pending.sort(key=lambda row: int(row.get("video_number", "9999")))
    data_root, data_available = resolve_data_root()
    report = {
        "csv_path": str(csv_path),
        "canonical_total": len(canonical_rows),
        "coded_and_backtested": done,
        "coded_modules_on_disk": sorted(coded_modules),
        "data_root": data_root,
        "data_available": data_available,
        "next_pending": pending[0] if pending else None,
    }
    print(json.dumps(report, indent=2))
    return report


def compute_composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0) or 0)
    if trades < min_trades:
        return 0.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0)
    win_rate = float(row.get("bt_win_rate", 0) or 0)
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    pnl = float(row.get("bt_total_pnl", 0) or 0)
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


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    resolved_root, data_available = resolve_data_root(data_root)
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)
    ensure_matrix_csv()

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    module_parts = strategy_cls.id.split("_", 1)
    module_id = module_parts[1] if len(module_parts) > 1 else strategy_cls.__module__.split(".")[-2]
    config_path = ROOT / "strategies" / module_id / "config.yaml"
    yaml_config = load_yaml_defaults(config_path)
    defaults = yaml_config.get("backtest_defaults", {})
    required_tf = [tf_from_string(item) for item in yaml_config.get("required_timeframes", [])]
    if not required_tf:
        required_tf = list(strategy_cls.timeframes)

    client = ExnessCSVClient(resolved_root)
    all_symbols = client.get_symbols()
    if symbols != "all":
        requested = [item.strip().upper() for item in symbols.split(",") if item.strip()]
        all_symbols = [symbol for symbol in all_symbols if symbol in requested]

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        module_id=module_id,
        video_number=str(yaml_config.get("video_number", strategy_cls.source_video)),
        instruments_scanned=len(all_symbols),
        data_root_used=resolved_root,
    )

    if not data_available:
        summary.data_source = "pending_exness_production"
        return summary

    instrument_results: list[InstrumentResult] = []
    for symbol in all_symbols:
        start_date, end_date = client.get_full_date_range(symbol, required_tf)
        if start_date is None or end_date is None:
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=None,
                    skipped=True,
                    data_quality_note="Missing required timeframe data",
                )
            )
            continue

        run_start = start or start_date
        run_end = end or end_date
        config = BacktestConfig(
            strategy_id=strategy_cls.id,
            symbol=symbol,
            start_date=run_start,
            end_date=run_end,
            initial_balance=float(defaults.get("initial_balance", 10000.0)),
            risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
            spread_pips=float(defaults.get("spread_pips", 1.0)),
            slippage_pips=float(defaults.get("slippage_pips", 0.5)),
            commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
        )
        strategy = strategy_cls()
        engine = BacktestEngine(config=config, strategy=strategy, client=client)
        result = engine.run()
        summary.instruments_tested += 1
        instrument_results.append(InstrumentResult(symbol=symbol, result=result))

    best_pnl = max(
        (float(item.result.total_pnl) for item in instrument_results if item.result is not None),
        default=0.0,
    )
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    matrix_rows: list[dict[str, Any]] = []

    for item in instrument_results:
        if item.skipped or item.result is None:
            matrix_rows.append(
                {
                    "strategy_registry_id": strategy_cls.id,
                    "strategy_module_id": module_id,
                    "video_number": summary.video_number,
                    "symbol": item.symbol,
                    "data_quality_note": item.data_quality_note,
                    "data_source": summary.data_source,
                    "backtested_at": now_iso,
                }
            )
            continue

        result = item.result
        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_id,
            "video_number": summary.video_number,
            "symbol": item.symbol,
            "backtest_start_date": result.config.start_date.date().isoformat(),
            "backtest_end_date": result.config.end_date.date().isoformat(),
            "bt_total_trades": result.total_trades,
            "bt_winning_trades": result.winning_trades,
            "bt_losing_trades": result.losing_trades,
            "bt_win_rate": result.win_rate,
            "bt_profit_factor": result.profit_factor,
            "bt_max_drawdown_pct": result.max_drawdown_pct,
            "bt_total_pnl": result.total_pnl,
            "bt_sharpe_ratio": result.sharpe_ratio,
            "bt_avg_rr": result.avg_rr,
            "bt_avg_trade_duration_mins": result.avg_trade_duration,
            "backtested_at": now_iso,
            "data_quality_note": "",
            "data_source": "exness_production",
        }
        row["composite_score"] = compute_composite_score(row, best_pnl)
        item.composite_score = row["composite_score"]
        result_json_path = output_path / strategy_cls.id / f"{item.symbol}.json"
        result_json_path.parent.mkdir(parents=True, exist_ok=True)
        with result_json_path.open("w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle, indent=2)
        row["backtest_result_json"] = str(result_json_path.relative_to(DOCUMENTS_ROOT))
        matrix_rows.append(row)

    ranked = sorted(
        [item for item in instrument_results if item.result is not None and item.composite_score > 0],
        key=lambda item: item.composite_score,
        reverse=True,
    )
    for rank, item in enumerate(ranked, start=1):
        for row in matrix_rows:
            if row.get("symbol") == item.symbol:
                row["rank_within_strategy"] = rank

    summary.matrix_rows = matrix_rows
    summary.data_source = "exness_production"
    tested_rows = [row for row in matrix_rows if row.get("bt_total_trades") is not None]
    if tested_rows:
        total_trades = sum(int(row.get("bt_total_trades", 0)) for row in tested_rows)
        total_wins = sum(int(row.get("bt_winning_trades", 0)) for row in tested_rows)
        total_pnl = sum(float(row.get("bt_total_pnl", 0)) for row in tested_rows)
        profit_factors = [float(row.get("bt_profit_factor", 0)) for row in tested_rows if row.get("bt_total_trades", 0)]
        max_dd = max(float(row.get("bt_max_drawdown_pct", 0)) for row in tested_rows)
        sharpes = [float(row.get("bt_sharpe_ratio", 0)) for row in tested_rows]
        avg_rrs = [float(row.get("bt_avg_rr", 0)) for row in tested_rows if row.get("bt_total_trades", 0)]
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0.0,
            "bt_profit_factor_all": round(sum(profit_factors) / len(profit_factors), 2) if profit_factors else 0.0,
            "bt_max_drawdown_pct_all": round(max_dd, 2),
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(sum(sharpes) / len(sharpes), 2) if sharpes else 0.0,
            "bt_avg_rr_all": round(sum(avg_rrs) / len(avg_rrs), 2) if avg_rrs else 0.0,
        }
        if ranked:
            best = ranked[0]
            worst = ranked[-1]
            summary.best_instrument = best.symbol
            summary.worst_instrument = worst.symbol
            best_row = next(row for row in matrix_rows if row["symbol"] == best.symbol)
            worst_row = next(row for row in matrix_rows if row["symbol"] == worst.symbol)
            summary.aggregate_stats.update(
                {
                    "best_instrument": best.symbol,
                    "best_instrument_pf": best_row.get("bt_profit_factor", 0),
                    "best_instrument_win_rate": best_row.get("bt_win_rate", 0),
                    "best_instrument_pnl": best_row.get("bt_total_pnl", 0),
                    "best_instrument_trades": best_row.get("bt_total_trades", 0),
                    "worst_instrument": worst.symbol,
                }
            )
            top_names = ", ".join(item.symbol for item in ranked[:3])
            summary.aggregate_stats["instrument_affinity_notes"] = (
                f"Top composite scores on {top_names}. "
                f"Strategy targets NY session VP absorption; Exness symbols used as NQ proxy universe."
            )

    _update_matrix_csv(matrix_rows, strategy_cls.id)
    return summary


def _update_matrix_csv(new_rows: list[dict[str, Any]], strategy_id: str):
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if MATRIX_CSV.exists():
        with MATRIX_CSV.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row
    for row in new_rows:
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        existing[key] = {column: row.get(column, "") for column in MATRIX_COLUMNS}
    with MATRIX_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        for key in sorted(existing.keys()):
            if key[0] == strategy_id or key[0]:
                writer.writerow(existing[key])


def update_tracking_csv(
    csv_path: Path,
    video_number: str,
    updates: dict[str, str],
    propagate_duplicates: bool = False,
):
    fieldnames, rows = read_csv_rows(csv_path)
    canonical_row = None
    for row in rows:
        if row.get("video_number") == video_number and row.get("action") == "CODE-CANONICAL":
            row.update(updates)
            canonical_row = row
    if propagate_duplicates and canonical_row and updates.get("data_source") == "exness_production":
        module = canonical_row.get("module_to_code", "")
        for row in rows:
            if row.get("action") == "DUPLICATE-SKIP" and row.get("module_to_code") == module:
                row["implementation_status"] = "covered_by_canonical"
                for key in updates:
                    if key.startswith("bt_") or key.startswith("best_") or key in {
                        "worst_instrument",
                        "instrument_affinity_notes",
                        "data_source",
                        "backtested_at",
                    }:
                        row[key] = updates[key]
    write_csv_atomic(csv_path, fieldnames, rows)


def cmd_run(args: argparse.Namespace) -> int:
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    _, data_available = resolve_data_root(args.data_root)
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if data_available and summary.data_source == "exness_production":
        status = "coded_and_backtested"
        data_source = "exness_production"
    else:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"

    updates = {
        "implementation_status": status,
        "strategy_module_id": summary.module_id,
        "strategy_folder": f"strategies/{summary.module_id}/",
        "strategy_registry_id": summary.strategy_id,
        "coded_at": now_iso,
        "backtested_at": now_iso if data_available else "",
        "instruments_tested_count": str(summary.instruments_tested),
        "anti_bias_review_passed": "yes",
        "anti_bias_notes": (
            "Uses closed M1 bars only; HTF feed gated by bar close; NY session via America/New_York; "
            "entries on bar close; stops/targets from VP structure not optimized on results."
        ),
        "data_source": data_source,
        "data_root_used": summary.data_root_used,
        **{key: str(value) for key, value in summary.aggregate_stats.items()},
    }
    update_tracking_csv(
        Path(args.csv),
        summary.video_number,
        updates,
        propagate_duplicates=data_source == "exness_production",
    )
    print(json.dumps({"summary": summary.__dict__}, indent=2, default=str))
    return 0


def cmd_list_strategies(_: argparse.Namespace) -> int:
    load_all_strategies(force=True)
    for item in list_strategy_metadata():
        print(f"{item['id']}\t{item['name']}\tvideo={item['source_video']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Audit CSV vs coded strategies")
    audit_parser.add_argument("--csv", default=str(DEFAULT_CSV))

    list_parser = subparsers.add_parser("list-strategies", help="List registered strategies")
    list_parser.set_defaults(func=cmd_list_strategies)

    run_parser = subparsers.add_parser("run", help="Run multi-instrument backtest")
    run_parser.add_argument("--strategy", required=True)
    run_parser.add_argument("--symbols", default="all")
    run_parser.add_argument("--data-root", default=None)
    run_parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_parser.add_argument("--csv", default=str(DEFAULT_CSV))
    run_parser.add_argument("--start", default=None)
    run_parser.add_argument("--end", default=None)
    run_parser.set_defaults(func=cmd_run)

    audit_parser.set_defaults(func=lambda args: 0 if audit_strategies(Path(args.csv)) is not None else 1)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
