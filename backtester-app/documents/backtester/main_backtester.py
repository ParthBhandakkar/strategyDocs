#!/usr/bin/env python3
"""
Main backtester CLI — audit, list strategies, and run multi-instrument backtests.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
DOCUMENTS = ROOT.parent
if str(DOCUMENTS) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS))

from backtester.connectors.exness_csv import ExnessCSVClient, resolve_data_root
from backtester.core import BacktestConfig, BacktestResult
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, list_strategy_ids

DEFAULT_CSV = DOCUMENTS / "video_docs" / "strategy_videos_90.csv"
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
    result: BacktestResult | None
    error: str = ""
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
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str = ""
    worst_instrument: str = ""
    instrument_affinity_notes: str = ""
    skip_reasons: dict[str, str] = field(default_factory=dict)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_yaml_config(strategy_module: str) -> dict[str, Any]:
    config_path = ROOT / "strategies" / strategy_module / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _ensure_csv_columns(csv_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for column in TRACKING_COLUMNS:
            if column not in fieldnames:
                fieldnames.append(column)
        for row in reader:
            for column in TRACKING_COLUMNS:
                row.setdefault(column, "")
            rows.append(row)
    return rows


def _write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    temp_path = csv_path.with_suffix(".csv.tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(csv_path)


def audit(csv_path: Path) -> dict[str, Any]:
    rows = _ensure_csv_columns(csv_path)
    fieldnames = list(rows[0].keys()) if rows else TRACKING_COLUMNS

    coded_folders = {
        path.name
        for path in (ROOT / "strategies").iterdir()
        if path.is_dir() and path.name not in {"__pycache__"}
    }
    canonical_rows = [
        row for row in rows if row.get("action") == "CODE-CANONICAL" and row.get("is_backtestable") == "yes"
    ]
    done = [
        row
        for row in canonical_rows
        if row.get("implementation_status") == "coded_and_backtested"
        and row.get("data_source") == "exness_production"
    ]
    pending = [
        row
        for row in canonical_rows
        if row.get("implementation_status") in {"", "not_started", "in_progress", "failed", "coded", "coded_pending_production_backtest"}
    ]

    data_root = resolve_data_root()
    symbol_count = 0
    if data_root:
        symbol_count = len(ExnessCSVClient(data_root).get_symbols())

    _write_csv_atomic(csv_path, fieldnames, rows)

    report = {
        "canonical_total": len(canonical_rows),
        "canonical_done": len(done),
        "canonical_pending": len(pending),
        "strategy_folders_on_disk": sorted(coded_folders),
        "registered_strategies": list_strategy_ids(),
        "data_root": data_root,
        "symbols_available": symbol_count,
        "main_backtester_exists": (ROOT / "main_backtester.py").exists(),
    }
    print(json.dumps(report, indent=2))
    return report


def list_strategies_cmd() -> None:
    for strategy_cls in get_all_strategies():
        print(f"{strategy_cls.id}\t{strategy_cls.name}\t{strategy_cls.__module__.split('.')[-2]}")


def _composite_score(
    profit_factor: float,
    win_rate: float,
    sharpe: float,
    pnl: float,
    trades: int,
    best_pnl: float,
) -> float:
    pf_norm = min(max(profit_factor, 0.0), 5.0) / 5.0
    wr_norm = min(max(win_rate, 0.0), 100.0) / 100.0
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    pnl_norm = min(max(pnl_norm, 0.0), 1.0)
    trade_norm = min(max(trades, 0), 50) / 50.0
    return round(
        pf_norm * 0.35 + wr_norm * 0.20 + sharpe_norm * 0.20 + pnl_norm * 0.15 + trade_norm * 0.10,
        4,
    )


def _load_strategy_config(strategy_cls) -> dict[str, Any]:
    module_name = strategy_cls.__module__.split(".")[-2]
    return _load_yaml_config(module_name)


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path = DEFAULT_OUTPUT,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    resolved_root = resolve_data_root(data_root)
    config = _load_strategy_config(strategy_cls)
    module_name = strategy_cls.__module__.split(".")[-2]
    defaults = config.get("backtest_defaults", {})
    required_tfs = [tf_from_string(item) for item in config.get("required_timeframes", ["M1"])]

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_name,
        video_number=str(config.get("video_number", "")),
        data_source="not_backtested",
        data_root_used=resolved_root or "",
    )

    if not resolved_root:
        summary.instrument_affinity_notes = (
            "Production backtest required on Windows with Exness structured history."
        )
        return summary

    client = ExnessCSVClient(resolved_root)
    all_symbols = client.get_symbols()
    summary.instruments_scanned = len(all_symbols)

    if isinstance(symbols, str):
        if symbols.lower() == "all":
            target_symbols = all_symbols
        else:
            target_symbols = [item.strip().upper() for item in symbols.split(",") if item.strip()]
    else:
        target_symbols = [item.upper() for item in symbols]

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    strategy_output = output_path / strategy_cls.id
    strategy_output.mkdir(parents=True, exist_ok=True)

    instrument_results: list[InstrumentResult] = []

    for symbol in target_symbols:
        available = client.list_available_timeframes(symbol)
        missing = [tf for tf in required_tfs if tf not in available]
        if missing:
            note = f"Missing timeframes: {', '.join(tf.name for tf in missing)}"
            summary.skip_reasons[symbol] = note
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(symbol=symbol, result=None, data_quality_note=note)
            )
            continue

        start_date, end_date = client.get_full_date_range(symbol, required_tfs)
        if start_date is None or end_date is None:
            note = "No bars in required timeframes"
            summary.skip_reasons[symbol] = note
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(symbol=symbol, result=None, data_quality_note=note)
            )
            continue

        bt_start = start or start_date
        bt_end = end or end_date

        bt_config = BacktestConfig(
            strategy_id=strategy_cls.id,
            symbol=symbol,
            start_date=bt_start,
            end_date=bt_end,
            initial_balance=float(defaults.get("initial_balance", 10000.0)),
            risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
            spread_pips=float(defaults.get("spread_pips", 1.0)),
            slippage_pips=float(defaults.get("slippage_pips", 0.5)),
            commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
        )

        try:
            engine = BacktestEngine(bt_config, strategy_cls(), client)
            result = engine.run()
            summary.instruments_tested += 1
            instrument_results.append(InstrumentResult(symbol=symbol, result=result))
            with (strategy_output / f"{symbol}.json").open("w", encoding="utf-8") as handle:
                json.dump(result.to_dict(), handle, indent=2)
        except Exception as exc:
            note = str(exc)
            summary.skip_reasons[symbol] = note
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(symbol=symbol, result=None, error=note, data_quality_note=note)
            )

    summary.data_source = "exness_production"
    summary.matrix_rows = _build_matrix_rows(
        summary,
        instrument_results,
        min_trades=int(config.get("min_trades_for_ranking", 10)),
    )
    summary.aggregate_stats = _aggregate_stats(summary.matrix_rows)
    summary.best_instrument, summary.worst_instrument, summary.instrument_affinity_notes = _affinity_summary(
        summary.matrix_rows,
        min_trades=int(config.get("min_trades_for_ranking", 10)),
    )
    _persist_matrix_csv(summary.matrix_rows)
    return summary


def _build_matrix_rows(
    summary: MultiInstrumentSummary,
    instrument_results: list[InstrumentResult],
    min_trades: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now_iso = _utc_now_iso()

    for item in instrument_results:
        if item.result is None:
            rows.append(
                {
                    "strategy_registry_id": summary.strategy_id,
                    "strategy_module_id": summary.strategy_module_id,
                    "video_number": summary.video_number,
                    "symbol": item.symbol,
                    "backtest_start_date": "",
                    "backtest_end_date": "",
                    "bt_total_trades": 0,
                    "bt_winning_trades": 0,
                    "bt_losing_trades": 0,
                    "bt_win_rate": 0,
                    "bt_profit_factor": 0,
                    "bt_max_drawdown_pct": 0,
                    "bt_total_pnl": 0,
                    "bt_sharpe_ratio": 0,
                    "bt_avg_rr": 0,
                    "bt_avg_trade_duration_mins": 0,
                    "composite_score": 0,
                    "rank_within_strategy": 0,
                    "backtest_result_json": "",
                    "backtested_at": now_iso,
                    "data_quality_note": item.data_quality_note or item.error,
                    "data_source": summary.data_source if item.result else "not_backtested",
                }
            )
            continue

        result = item.result
        stats = result.to_dict()["stats"]
        rows.append(
            {
                "strategy_registry_id": summary.strategy_id,
                "strategy_module_id": summary.strategy_module_id,
                "video_number": summary.video_number,
                "symbol": item.symbol,
                "backtest_start_date": result.config.start_date.date().isoformat(),
                "backtest_end_date": result.config.end_date.date().isoformat(),
                "bt_total_trades": stats["total_trades"],
                "bt_winning_trades": stats["winning_trades"],
                "bt_losing_trades": stats["losing_trades"],
                "bt_win_rate": stats["win_rate"],
                "bt_profit_factor": stats["profit_factor"],
                "bt_max_drawdown_pct": stats["max_drawdown_pct"],
                "bt_total_pnl": stats["total_pnl"],
                "bt_sharpe_ratio": stats["sharpe_ratio"],
                "bt_avg_rr": stats["avg_rr"],
                "bt_avg_trade_duration_mins": stats["avg_trade_duration_mins"],
                "composite_score": 0,
                "rank_within_strategy": 0,
                "backtest_result_json": json.dumps(result.to_dict()),
                "backtested_at": now_iso,
                "data_quality_note": item.data_quality_note,
                "data_source": summary.data_source,
            }
        )

    best_pnl = max((float(row["bt_total_pnl"]) for row in rows), default=0.0)
    for row in rows:
        row["composite_score"] = _composite_score(
            float(row["bt_profit_factor"] or 0),
            float(row["bt_win_rate"] or 0),
            float(row["bt_sharpe_ratio"] or 0),
            float(row["bt_total_pnl"] or 0),
            int(float(row["bt_total_trades"] or 0)),
            best_pnl,
        )

    ranked = sorted(rows, key=lambda row: row["composite_score"], reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = index
    return ranked


def _aggregate_stats(matrix_rows: list[dict[str, Any]]) -> dict[str, Any]:
    tested = [row for row in matrix_rows if int(float(row.get("bt_total_trades", 0))) > 0]
    if not tested:
        return {
            "bt_total_trades_all": 0,
            "bt_win_rate_all": 0,
            "bt_profit_factor_all": 0,
            "bt_max_drawdown_pct_all": 0,
            "bt_total_pnl_all": 0,
            "bt_sharpe_ratio_all": 0,
            "bt_avg_rr_all": 0,
        }

    total_trades = sum(int(float(row["bt_total_trades"])) for row in tested)
    total_wins = sum(int(float(row["bt_winning_trades"])) for row in tested)
    gross_profit = sum(float(row["bt_total_pnl"]) for row in tested if float(row["bt_total_pnl"]) > 0)
    gross_loss = abs(sum(float(row["bt_total_pnl"]) for row in tested if float(row["bt_total_pnl"]) <= 0))
    return {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0,
        "bt_profit_factor_all": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
        "bt_max_drawdown_pct_all": round(max(float(row["bt_max_drawdown_pct"]) for row in tested), 2),
        "bt_total_pnl_all": round(sum(float(row["bt_total_pnl"]) for row in tested), 2),
        "bt_sharpe_ratio_all": round(
            sum(float(row["bt_sharpe_ratio"]) for row in tested) / len(tested),
            2,
        ),
        "bt_avg_rr_all": round(
            sum(float(row["bt_avg_rr"]) for row in tested) / len(tested),
            2,
        ),
    }


def _affinity_summary(
    matrix_rows: list[dict[str, Any]],
    min_trades: int,
) -> tuple[str, str, str]:
    eligible = [
        row
        for row in matrix_rows
        if int(float(row.get("bt_total_trades", 0))) >= min_trades
    ]
    if not eligible:
        return "", "", "Insufficient trades across instruments for affinity ranking."

    best = max(eligible, key=lambda row: row["composite_score"])
    worst = min(eligible, key=lambda row: row["composite_score"])
    strong = [row for row in eligible if float(row["bt_profit_factor"]) >= 1.2][:3]
    weak = [row for row in eligible if float(row["bt_profit_factor"]) < 1.0][:3]
    notes = (
        f"Strong on {', '.join(row['symbol'] for row in strong) or best['symbol']} "
        f"(PF>1.2). Weak on {', '.join(row['symbol'] for row in weak) or worst['symbol']}."
    )
    return best["symbol"], worst["symbol"], notes


def _persist_matrix_csv(matrix_rows: list[dict[str, Any]]) -> None:
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if MATRIX_CSV.exists():
        with MATRIX_CSV.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for row in matrix_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {column: str(row.get(column, "")) for column in MATRIX_COLUMNS}

    with MATRIX_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda item: (item["strategy_registry_id"], item["symbol"])):
            writer.writerow(row)


def update_tracking_csv(
    csv_path: Path,
    video_number: str,
    updates: dict[str, str],
    propagate_duplicate: bool = False,
) -> None:
    rows = _ensure_csv_columns(csv_path)
    fieldnames = list(rows[0].keys()) if rows else TRACKING_COLUMNS

    canonical_row = None
    for row in rows:
        if row.get("video_number") == str(video_number):
            row.update({key: str(value) for key, value in updates.items()})
            if row.get("action") == "CODE-CANONICAL":
                canonical_row = row

    if propagate_duplicate and canonical_row:
        module = canonical_row.get("module_to_code", "")
        for row in rows:
            if row.get("action") == "DUPLICATE-SKIP" and row.get("module_to_code") == module:
                row["implementation_status"] = "covered_by_canonical"
                for key in TRACKING_COLUMNS:
                    if key.startswith("bt_") or key.startswith("best_") or key in {
                        "worst_instrument",
                        "instrument_affinity_notes",
                        "data_source",
                        "backtested_at",
                    }:
                        row[key] = canonical_row.get(key, "")

    _write_csv_atomic(csv_path, fieldnames, rows)


def run_cmd(args: argparse.Namespace) -> None:
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    print(json.dumps(
        {
            "strategy_id": summary.strategy_id,
            "data_source": summary.data_source,
            "data_root_used": summary.data_root_used,
            "instruments_scanned": summary.instruments_scanned,
            "instruments_tested": summary.instruments_tested,
            "instruments_skipped": summary.instruments_skipped,
            "aggregate_stats": summary.aggregate_stats,
            "best_instrument": summary.best_instrument,
            "worst_instrument": summary.worst_instrument,
            "instrument_affinity_notes": summary.instrument_affinity_notes,
            "skip_reasons": summary.skip_reasons,
        },
        indent=2,
    ))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy backtester")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Audit CSV vs disk vs registry")
    audit_parser.add_argument("--csv", default=str(DEFAULT_CSV))

    subparsers.add_parser("list-strategies", help="List registered strategies")

    run_parser = subparsers.add_parser("run", help="Run multi-instrument backtest")
    run_parser.add_argument("--strategy", required=True)
    run_parser.add_argument("--symbols", default="all")
    run_parser.add_argument("--data-root", default=None)
    run_parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_parser.add_argument("--start", default=None)
    run_parser.add_argument("--end", default=None)
    run_parser.set_defaults(func=run_cmd)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "audit":
        audit(Path(args.csv))
    elif args.command == "list-strategies":
        list_strategies_cmd()
    elif hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
