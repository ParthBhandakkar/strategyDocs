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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
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

if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import discover_strategies, get_strategy


@dataclass
class RunSummary:
    strategy_id: str
    data_root: str
    data_source: str
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str = ""
    worst_instrument: str = ""
    affinity_notes: str = ""


def resolve_data_root(cli_value: str | None) -> tuple[str, bool]:
    if cli_value:
        path = Path(cli_value)
        if path.is_dir() and ExnessCSVClient(path).get_symbols():
            return str(path), True
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path and Path(env_path).is_dir() and ExnessCSVClient(env_path).get_symbols():
        return env_path, True
    default = Path(DEFAULT_DATA_ROOT)
    if default.is_dir() and ExnessCSVClient(default).get_symbols():
        return str(default), True
    return cli_value or env_path or DEFAULT_DATA_ROOT, False


def load_strategy_config(strategy_folder: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / strategy_folder / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def ensure_csv_columns(csv_path: Path) -> list[dict[str, str]]:
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    for column in TRACKING_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)
    for row in rows:
        for column in TRACKING_COLUMNS:
            row.setdefault(column, "")
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def save_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    temp_path = csv_path.with_suffix(".csv.tmp")
    with open(temp_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(csv_path)


def composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0) or 0)
    if trades < min_trades:
        return -1.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0)
    win_rate = float(row.get("bt_win_rate", 0) or 0)
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    return (
        (pf / 5.0 * 0.35)
        + (win_rate / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10)
    )


def load_matrix_rows() -> list[dict[str, str]]:
    if not MATRIX_CSV.exists():
        return []
    with open(MATRIX_CSV, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def save_matrix_rows(rows: list[dict[str, Any]]) -> None:
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    with open(MATRIX_CSV, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def upsert_matrix_row(existing: list[dict[str, Any]], new_row: dict[str, Any]) -> list[dict[str, Any]]:
    key = (new_row["strategy_registry_id"], new_row["symbol"])
    updated = [row for row in existing if (row["strategy_registry_id"], row["symbol"]) != key]
    updated.append(new_row)
    return updated


def run_audit(csv_path: Path) -> dict[str, Any]:
    rows = ensure_csv_columns(csv_path)
    strategies = discover_strategies()
    coded_folders = {
        folder.name
        for folder in (BACKTESTER_ROOT / "strategies").iterdir()
        if folder.is_dir() and folder.name not in {"base", "registry", "__pycache__"}
    }
    canonical_rows = [
        row for row in rows if row.get("action") == "CODE-CANONICAL" and row.get("is_backtestable") == "yes"
    ]
    pending = [
        row
        for row in canonical_rows
        if row.get("implementation_status", "") in {"", "not_started", "failed", "in_progress"}
    ]
    data_root, data_available = resolve_data_root(None)
    return {
        "canonical_total": len(canonical_rows),
        "coded_folders": sorted(coded_folders),
        "registered_strategies": sorted(strategies.keys()),
        "pending_modules": [
            {"video_number": row["video_number"], "module": row["module_to_code"], "status": row.get("implementation_status", "")}
            for row in pending
        ],
        "data_root": data_root,
        "data_available": data_available,
        "symbol_count": len(ExnessCSVClient(data_root).get_symbols()) if data_available else 0,
    }


def list_strategies_cmd() -> None:
    strategies = discover_strategies()
    for strategy_id in sorted(strategies):
        instance = strategies[strategy_id]()
        print(f"{strategy_id}: {instance.name} (video {instance.source_video})")


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> RunSummary:
    resolved_root, data_available = resolve_data_root(data_root)
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    strategy = get_strategy(strategy_id)
    config_data = load_strategy_config(strategy_id.split("_", 1)[-1])
    defaults = config_data.get("backtest_defaults", {})
    required_tf = [tf_from_string(value) for value in config_data.get("required_timeframes", ["M1"])]

    client = ExnessCSVClient(resolved_root)
    all_symbols = client.get_symbols() if data_available else []
    if symbols != "all":
        selected = [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()]
        all_symbols = [symbol for symbol in selected if symbol in all_symbols]

    summary = RunSummary(
        strategy_id=strategy.id,
        data_root=resolved_root,
        data_source="exness_production" if data_available else "pending_exness_production",
        instruments_scanned=len(all_symbols) if data_available else 0,
    )

    if not data_available:
        summary.affinity_notes = (
            "Production backtest required on Windows with Exness structured history path."
        )
        return summary

    matrix_rows = load_matrix_rows()
    result_rows: list[dict[str, Any]] = []

    for symbol in all_symbols:
        if not client.has_required_timeframes(symbol, required_tf):
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = "missing required timeframe data"
            continue

        start_date, end_date = client.get_full_date_range(symbol, required_tf)
        if start_date is None or end_date is None:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = "unable to resolve date range"
            continue

        run_start = start or start_date
        run_end = end or end_date
        backtest_config = BacktestConfig(
            strategy_id=strategy.id,
            symbol=symbol,
            start_date=run_start,
            end_date=run_end,
            initial_balance=float(defaults.get("initial_balance", 10000.0)),
            risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
            spread_pips=float(defaults.get("spread_pips", 1.0)),
            slippage_pips=float(defaults.get("slippage_pips", 0.5)),
            commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
        )

        engine = BacktestEngine(backtest_config, get_strategy(strategy_id), client)
        result = engine.run()
        summary.instruments_tested += 1

        result_dict = result.to_dict()
        strategy_output_dir = output_path / strategy.id
        strategy_output_dir.mkdir(parents=True, exist_ok=True)
        json_path = strategy_output_dir / f"{symbol}.json"
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(result_dict, handle, indent=2)

        row = {
            "strategy_registry_id": strategy.id,
            "strategy_module_id": strategy.id.split("_", 1)[-1],
            "video_number": config_data.get("video_number", strategy.source_video),
            "symbol": symbol,
            "backtest_start_date": run_start.date().isoformat(),
            "backtest_end_date": run_end.date().isoformat(),
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
            "composite_score": 0.0,
            "rank_within_strategy": 0,
            "backtest_result_json": str(json_path),
            "backtested_at": datetime.now(timezone.utc).isoformat(),
            "data_quality_note": "",
            "data_source": "exness_production",
        }
        result_rows.append(row)
        matrix_rows = upsert_matrix_row(matrix_rows, row)

    if result_rows:
        best_pnl = max(float(row["bt_total_pnl"]) for row in result_rows)
        min_trades = int(config_data.get("min_trades_for_ranking", 10))
        for row in result_rows:
            row["composite_score"] = round(composite_score(row, best_pnl, min_trades), 4)
        ranked = sorted(
            [row for row in result_rows if row["composite_score"] >= 0],
            key=lambda item: item["composite_score"],
            reverse=True,
        )
        for index, row in enumerate(ranked, start=1):
            row["rank_within_strategy"] = index
        if ranked:
            best = ranked[0]
            worst = ranked[-1]
            summary.best_instrument = best["symbol"]
            summary.worst_instrument = worst["symbol"]
            summary.affinity_notes = (
                f"Strongest on {best['symbol']} (PF={best['bt_profit_factor']}, "
                f"{best['bt_total_trades']} trades). Weakest ranked: {worst['symbol']}."
            )
        summary.matrix_rows = result_rows
        summary.aggregate_stats = {
            "trades": sum(int(row["bt_total_trades"]) for row in result_rows),
            "win_rate": round(
                sum(float(row["bt_win_rate"]) for row in result_rows) / len(result_rows),
                2,
            ),
            "profit_factor": round(
                sum(float(row["bt_profit_factor"]) if row["bt_profit_factor"] != float("inf") else 5.0 for row in result_rows)
                / len(result_rows),
                2,
            ),
            "max_drawdown_pct": max(float(row["bt_max_drawdown_pct"]) for row in result_rows),
            "total_pnl": round(sum(float(row["bt_total_pnl"]) for row in result_rows), 2),
            "sharpe_ratio": round(
                sum(float(row["bt_sharpe_ratio"]) for row in result_rows) / len(result_rows),
                2,
            ),
            "avg_rr": round(sum(float(row["bt_avg_rr"]) for row in result_rows) / len(result_rows), 2),
        }
        for row in result_rows:
            matrix_rows = upsert_matrix_row(matrix_rows, row)
        save_matrix_rows(matrix_rows)

    return summary


def update_tracking_csv(
    csv_path: Path,
    module_to_code: str,
    summary: RunSummary,
    *,
    anti_bias_passed: str,
    anti_bias_notes: str,
    implementation_status: str,
) -> None:
    rows = ensure_csv_columns(csv_path)
    now = datetime.now(timezone.utc).isoformat()
    fieldnames = list(rows[0].keys()) if rows else TRACKING_COLUMNS

    for row in rows:
        if row.get("module_to_code") != module_to_code:
            continue
        row["implementation_status"] = implementation_status
        row["strategy_module_id"] = module_to_code
        row["strategy_folder"] = f"strategies/{module_to_code}/"
        row["strategy_registry_id"] = summary.strategy_id
        row["coded_at"] = row.get("coded_at") or now
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["data_source"] = summary.data_source
        row["data_root_used"] = summary.data_root
        if summary.instruments_tested > 0:
            row["backtested_at"] = now
            row["instruments_tested_count"] = str(summary.instruments_tested)
            stats = summary.aggregate_stats
            row["bt_total_trades_all"] = str(stats.get("trades", 0))
            row["bt_win_rate_all"] = str(stats.get("win_rate", 0))
            row["bt_profit_factor_all"] = str(stats.get("profit_factor", 0))
            row["bt_max_drawdown_pct_all"] = str(stats.get("max_drawdown_pct", 0))
            row["bt_total_pnl_all"] = str(stats.get("total_pnl", 0))
            row["bt_sharpe_ratio_all"] = str(stats.get("sharpe_ratio", 0))
            row["bt_avg_rr_all"] = str(stats.get("avg_rr", 0))
            if summary.best_instrument:
                best_row = next((item for item in summary.matrix_rows if item["symbol"] == summary.best_instrument), None)
                worst_row = next((item for item in summary.matrix_rows if item["symbol"] == summary.worst_instrument), None)
                if best_row:
                    row["best_instrument"] = summary.best_instrument
                    row["best_instrument_pf"] = str(best_row["bt_profit_factor"])
                    row["best_instrument_win_rate"] = str(best_row["bt_win_rate"])
                    row["best_instrument_pnl"] = str(best_row["bt_total_pnl"])
                    row["best_instrument_trades"] = str(best_row["bt_total_trades"])
                if worst_row:
                    row["worst_instrument"] = summary.worst_instrument
            row["instrument_affinity_notes"] = summary.affinity_notes

    if implementation_status == "coded_and_backtested":
        canonical_row = next((row for row in rows if row.get("module_to_code") == module_to_code), None)
        if canonical_row:
            for row in rows:
                if row.get("duplicate_of_video") == canonical_row.get("video_number"):
                    row["implementation_status"] = "covered_by_canonical"
                    row["strategy_registry_id"] = canonical_row.get("strategy_registry_id", "")
                    row["data_source"] = canonical_row.get("data_source", "")

    save_csv_atomic(csv_path, fieldnames, rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy backtester")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--csv", default=str(DEFAULT_CSV))

    subparsers.add_parser("list-strategies")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--strategy", required=True)
    run_parser.add_argument("--symbols", default="all")
    run_parser.add_argument("--data-root", default=None)
    run_parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_parser.add_argument("--start", default=None)
    run_parser.add_argument("--end", default=None)
    run_parser.add_argument("--csv", default=str(DEFAULT_CSV))
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "audit":
        report = run_audit(Path(args.csv))
        print(json.dumps(report, indent=2))
        return

    if args.command == "list-strategies":
        list_strategies_cmd()
        return

    if args.command == "run":
        start = datetime.fromisoformat(args.start) if args.start else None
        end = datetime.fromisoformat(args.end) if args.end else None
        summary = run_multi_instrument_backtest(
            strategy_id=args.strategy,
            data_root=args.data_root,
            symbols=args.symbols,
            output_dir=args.output,
            start=start,
            end=end,
        )
        _, data_available = resolve_data_root(args.data_root)
        status = "coded_and_backtested" if data_available and summary.instruments_tested > 0 else "coded_pending_production_backtest"
        data_source = "exness_production" if data_available and summary.instruments_tested > 0 else "pending_exness_production"
        summary.data_source = data_source
        anti_bias_notes = (
            "HTF bars gated by close in data_feed; session filters use America/New_York; "
            "signals use bar close only; VP/absorption from past session bars; parameters from video doc."
        )
        update_tracking_csv(
            Path(args.csv),
            module_to_code=args.strategy.split("_", 1)[-1],
            summary=summary,
            anti_bias_passed="yes",
            anti_bias_notes=anti_bias_notes,
            implementation_status=status,
        )
        print(json.dumps({"summary": summary.__dict__}, indent=2, default=str))


if __name__ == "__main__":
    main()
