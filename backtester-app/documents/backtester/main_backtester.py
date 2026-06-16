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
from typing import Any

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"

if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig, BacktestResult
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies


@dataclass
class InstrumentResult:
    symbol: str
    result: BacktestResult | None
    composite_score: float = 0.0
    rank_within_strategy: int = 0
    data_quality_note: str = ""
    skipped: bool = False


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: int
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str = ""
    worst_instrument: str = ""
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_root_used: str = ""
    data_source: str = "not_backtested"


def resolve_data_root(cli_data_root: str | None) -> Path:
    if cli_data_root:
        return Path(cli_data_root)
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path and Path(env_path).is_dir():
        client = ExnessCSVClient(env_path)
        if client.get_symbols():
            return Path(env_path)
    return Path(DEFAULT_DATA_ROOT)


def load_strategy_config(strategy_cls) -> dict[str, Any]:
    import inspect

    config_path = Path(inspect.getfile(strategy_cls)).parent / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    with open(config_path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def compute_composite_score(
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
    pnl_norm = max(pnl, 0.0) / best_pnl if best_pnl > 0 else 0.0
    trades_norm = min(trades, 50) / 50.0
    return round(
        pf_norm * 0.35
        + wr_norm * 0.20
        + sharpe_norm * 0.20
        + pnl_norm * 0.15
        + trades_norm * 0.10,
        4,
    )


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    start: datetime | None = None,
    end: datetime | None = None,
) -> InstrumentResult:
    config_data = load_strategy_config(strategy_cls)
    defaults = config_data.get("backtest_defaults", {})
    required_tfs = [tf_from_string(tf_name) for tf_name in config_data.get("required_timeframes", [])]
    if not required_tfs:
        required_tfs = list(strategy_cls.timeframes)

    missing = [tf.name for tf in required_tfs if not client.has_timeframe(symbol, tf)]
    if missing:
        return InstrumentResult(
            symbol=symbol,
            result=None,
            skipped=True,
            data_quality_note=f"Missing timeframes: {', '.join(missing)}",
        )

    full_start, full_end = client.get_full_date_range(symbol, required_tfs)
    if full_start is None or full_end is None:
        return InstrumentResult(
            symbol=symbol,
            result=None,
            skipped=True,
            data_quality_note="No date range available",
        )

    start_date = start or full_start
    end_date = end or full_end

    from backtester.core.engine import BacktestEngine

    strategy = strategy_cls()
    config = BacktestConfig(
        strategy_id=strategy.id,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_balance=float(defaults.get("initial_balance", 10000.0)),
        risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(defaults.get("spread_pips", 1.0)),
        slippage_pips=float(defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
    )
    engine = BacktestEngine(config=config, strategy=strategy, client=client)
    result = engine.run()

    strategy_output = output_dir / strategy.id
    strategy_output.mkdir(parents=True, exist_ok=True)
    with open(strategy_output / f"{symbol}.json", "w", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2)

    return InstrumentResult(symbol=symbol, result=result)


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path,
    symbols: str | list[str] = "all",
    output_dir: str | Path = DEFAULT_OUTPUT,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    data_root_path = Path(data_root)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    config_data = load_strategy_config(strategy_cls)
    client = ExnessCSVClient(data_root_path)
    available_symbols = client.get_symbols()

    if symbols == "all":
        target_symbols = available_symbols
    elif isinstance(symbols, str):
        target_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        target_symbols = [s.upper() for s in symbols]

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=config_data.get("module", strategy_cls.__module__.split(".")[-1]),
        video_number=int(config_data.get("video_number", strategy_cls.source_video or 0)),
        instruments_scanned=len(target_symbols),
        data_root_used=str(data_root_path),
    )

    if not data_root_path.is_dir() or not available_symbols:
        summary.data_source = "not_backtested"
        summary.instruments_skipped = len(target_symbols)
        return summary

    summary.data_source = "exness_production"
    instrument_results: list[InstrumentResult] = []

    for symbol in target_symbols:
        if symbol not in available_symbols:
            instrument_results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=None,
                    skipped=True,
                    data_quality_note="Symbol folder not found under data root",
                )
            )
            continue
        instrument_results.append(
            run_single_symbol_backtest(strategy_cls, symbol, client, output_path, start, end)
        )

    tested = [item for item in instrument_results if item.result is not None]
    skipped = [item for item in instrument_results if item.skipped]
    summary.instruments_tested = len(tested)
    summary.instruments_skipped = len(skipped)

    best_pnl = max((item.result.total_pnl for item in tested), default=0.0)
    if best_pnl <= 0:
        best_pnl = max((abs(item.result.total_pnl) for item in tested), default=1.0)

    min_trades = int(config_data.get("min_trades_for_ranking", 10))
    ranking_candidates: list[InstrumentResult] = []

    for item in tested:
        result = item.result
        assert result is not None
        item.composite_score = compute_composite_score(
            profit_factor=result.profit_factor if result.profit_factor != float("inf") else 5.0,
            win_rate=result.win_rate,
            sharpe=result.sharpe_ratio,
            pnl=result.total_pnl,
            trades=result.total_trades,
            best_pnl=best_pnl,
        )
        if result.total_trades >= min_trades:
            ranking_candidates.append(item)

    ranking_candidates.sort(key=lambda x: x.composite_score, reverse=True)
    for rank, item in enumerate(ranking_candidates, start=1):
        item.rank_within_strategy = rank

    now_iso = datetime.now(timezone.utc).isoformat()
    matrix_rows: list[dict[str, Any]] = []
    for item in instrument_results:
        if item.result is None:
            matrix_rows.append(
                {
                    "strategy_registry_id": strategy_cls.id,
                    "strategy_module_id": summary.strategy_module_id,
                    "video_number": summary.video_number,
                    "symbol": item.symbol,
                    "backtest_start_date": "",
                    "backtest_end_date": "",
                    "bt_total_trades": 0,
                    "bt_winning_trades": 0,
                    "bt_losing_trades": 0,
                    "bt_win_rate": 0.0,
                    "bt_profit_factor": 0.0,
                    "bt_max_drawdown_pct": 0.0,
                    "bt_total_pnl": 0.0,
                    "bt_sharpe_ratio": 0.0,
                    "bt_avg_rr": 0.0,
                    "bt_avg_trade_duration_mins": 0.0,
                    "composite_score": 0.0,
                    "rank_within_strategy": 0,
                    "backtest_result_json": "",
                    "backtested_at": now_iso,
                    "data_quality_note": item.data_quality_note,
                    "data_source": summary.data_source,
                }
            )
            continue

        result = item.result
        matrix_rows.append(
            {
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": summary.strategy_module_id,
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
                "bt_total_pnl": round(result.total_pnl, 2),
                "bt_sharpe_ratio": result.sharpe_ratio,
                "bt_avg_rr": result.avg_rr,
                "bt_avg_trade_duration_mins": result.avg_trade_duration,
                "composite_score": item.composite_score,
                "rank_within_strategy": item.rank_within_strategy,
                "backtest_result_json": str(output_path / strategy_cls.id / f"{item.symbol}.json"),
                "backtested_at": now_iso,
                "data_quality_note": item.data_quality_note,
                "data_source": summary.data_source,
            }
        )

    summary.matrix_rows = matrix_rows
    update_strategy_matrix(output_path / "strategy_instrument_matrix.csv", matrix_rows)

    if ranking_candidates:
        summary.best_instrument = ranking_candidates[0].symbol
        summary.worst_instrument = ranking_candidates[-1].symbol

    if tested:
        total_trades = sum(item.result.total_trades for item in tested if item.result)
        total_wins = sum(item.result.winning_trades for item in tested if item.result)
        gross_profit = sum(
            max(item.result.total_pnl, 0.0) for item in tested if item.result and item.result.total_pnl > 0
        )
        gross_loss = abs(
            sum(
                min(item.result.total_pnl, 0.0)
                for item in tested
                if item.result and item.result.total_pnl <= 0
            )
        )
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0.0,
            "bt_profit_factor_all": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0,
            "bt_max_drawdown_pct_all": max(
                (item.result.max_drawdown_pct for item in tested if item.result), default=0.0
            ),
            "bt_total_pnl_all": round(sum(item.result.total_pnl for item in tested if item.result), 2),
            "bt_sharpe_ratio_all": round(
                sum(item.result.sharpe_ratio for item in tested if item.result) / len(tested), 2
            ),
            "bt_avg_rr_all": round(
                sum(item.result.avg_rr for item in tested if item.result) / len(tested), 2
            ),
        }

    return summary


def update_strategy_matrix(matrix_path: Path, new_rows: list[dict[str, Any]]):
    columns = [
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

    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if matrix_path.exists():
        with open(matrix_path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {column: str(row.get(column, "")) for column in columns}

    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=columns)
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda r: (r["strategy_registry_id"], r["symbol"])):
            writer.writerow(row)
        temp_name = tmp.name
    os.replace(temp_name, matrix_path)


def audit_csv(csv_path: Path) -> dict[str, Any]:
    load_all_strategies()
    registry = {cls.id: cls for cls in get_all_strategies()}

    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    tracking_columns = [
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
    missing_columns = [column for column in tracking_columns if column not in fieldnames]

    canonical_rows = [
        row for row in rows if row.get("action") == "CODE-CANONICAL" and row.get("is_backtestable") == "yes"
    ]
    coded = [
        row
        for row in canonical_rows
        if row.get("implementation_status") in {"coded_and_backtested", "coded_pending_production_backtest", "coded"}
    ]

    data_root = resolve_data_root(None)
    symbols = ExnessCSVClient(data_root).get_symbols() if data_root.is_dir() else []

    report = {
        "csv_path": str(csv_path),
        "missing_columns": missing_columns,
        "registered_strategies": list(registry.keys()),
        "canonical_total": len(canonical_rows),
        "canonical_started": len(coded),
        "data_root": str(data_root),
        "data_root_exists": data_root.is_dir(),
        "symbol_count": len(symbols),
    }
    print(json.dumps(report, indent=2))
    return report


def ensure_csv_columns(csv_path: Path):
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    extra_columns = [
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
    changed = False
    for column in extra_columns:
        if column not in fieldnames:
            fieldnames.append(column)
            changed = True
            for row in rows:
                row[column] = row.get(column, "")

    if changed:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False) as tmp:
            writer = csv.DictWriter(tmp, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            temp_name = tmp.name
        os.replace(temp_name, csv_path)


def update_tracking_csv(
    csv_path: Path,
    module_to_code: str,
    updates: dict[str, str],
    propagate_duplicates: bool = False,
):
    ensure_csv_columns(csv_path)
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    now_iso = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("module_to_code") == module_to_code and row.get("action") == "CODE-CANONICAL":
            for key, value in updates.items():
                row[key] = value
            if not row.get("coded_at") and updates.get("implementation_status", "").startswith("coded"):
                row["coded_at"] = now_iso
        elif propagate_duplicates and row.get("duplicate_of_video"):
            canonical_video = row.get("duplicate_of_video")
            canonical_row = next(
                (
                    candidate
                    for candidate in rows
                    if candidate.get("video_number") == canonical_video
                    and candidate.get("action") == "CODE-CANONICAL"
                ),
                None,
            )
            if canonical_row and canonical_row.get("module_to_code") == module_to_code:
                if canonical_row.get("implementation_status") == "coded_and_backtested":
                    row["implementation_status"] = "covered_by_canonical"
                    for key in updates:
                        if key.startswith("bt_") or key.startswith("best_") or key.startswith("worst_"):
                            row[key] = updates[key]

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        temp_name = tmp.name
    os.replace(temp_name, csv_path)


def cmd_audit(args: argparse.Namespace):
    csv_path = Path(args.csv)
    ensure_csv_columns(csv_path)
    audit_csv(csv_path)


def cmd_list_strategies(_: argparse.Namespace):
    strategies = get_all_strategies()
    for strategy_cls in sorted(strategies, key=lambda cls: cls.id):
        print(f"{strategy_cls.id:40} {strategy_cls.name}")


def cmd_run(args: argparse.Namespace):
    data_root = resolve_data_root(args.data_root)
    output_dir = Path(args.output)
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=data_root,
        symbols=args.symbols,
        output_dir=output_dir,
    )
    print(json.dumps(summary.__dict__, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy backtester pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Audit CSV tracking vs coded strategies")
    audit_parser.add_argument("--csv", default=str(DEFAULT_CSV))
    audit_parser.set_defaults(func=cmd_audit)

    list_parser = subparsers.add_parser("list-strategies", help="List registered strategies")
    list_parser.set_defaults(func=cmd_list_strategies)

    run_parser = subparsers.add_parser("run", help="Run a multi-instrument backtest")
    run_parser.add_argument("--strategy", required=True)
    run_parser.add_argument("--symbols", default="all")
    run_parser.add_argument("--data-root", default=None)
    run_parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_parser.add_argument("--start", default=None)
    run_parser.add_argument("--end", default=None)
    run_parser.set_defaults(func=cmd_run)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
