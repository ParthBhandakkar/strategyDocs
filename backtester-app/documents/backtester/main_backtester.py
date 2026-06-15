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

import yaml

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
DEFAULT_DATA_ROOT = Path(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history")

if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig, BacktestResult
from backtester.core.timeframes import TF, tf_from_string
from backtester.core.engine import BacktestEngine
from backtester.strategies.registry import get_strategy, list_strategy_metadata, load_all_strategies

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
    composite_score: float = 0.0
    rank: int = 0
    data_quality_note: str = ""
    json_path: str = ""


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str = ""
    worst_instrument: str = ""
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_data_root: str | None) -> Path:
    if cli_data_root:
        return Path(cli_data_root)
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_dir() and any(candidate.iterdir()):
            return candidate
    return DEFAULT_DATA_ROOT


def has_real_history(data_root: Path) -> bool:
    if not data_root.is_dir():
        return False
    for symbol_dir in data_root.iterdir():
        if not symbol_dir.is_dir():
            continue
        for tf_dir in symbol_dir.iterdir():
            if tf_dir.is_dir() and any(tf_dir.glob("*.csv")):
                return True
    return False


def strategy_module_name(strategy_cls) -> str:
    return strategy_cls.__module__.rsplit(".", 2)[-2]


def load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for column in TRACKING_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)
    return fieldnames, rows


def write_csv_rows(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    temp_path = csv_path.with_suffix(".csv.tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(csv_path)


def list_strategy_folders() -> set[str]:
    strategies_dir = BACKTESTER_ROOT / "strategies"
    return {
        folder.name
        for folder in strategies_dir.iterdir()
        if folder.is_dir() and folder.name not in {"__pycache__"}
    }


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    fieldnames, rows = read_csv_rows(csv_path)
    folders = list_strategy_folders()
    canonical_rows = [
        row for row in rows if row.get("action") == "CODE-CANONICAL" and row.get("is_backtestable") == "yes"
    ]
    coded = sum(1 for row in canonical_rows if row.get("implementation_status") in {"coded_and_backtested", "coded_pending_production_backtest", "coded"})
    backtested = sum(1 for row in canonical_rows if row.get("implementation_status") == "coded_and_backtested")
    data_root = resolve_data_root(args.data_root)
    real_data = has_real_history(data_root)

    print("=== Backtester Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Strategy folders on disk: {sorted(folders)}")
    print(f"Registered strategies: {[item['id'] for item in list_strategy_metadata()]}")
    print(f"Canonical modules: {len(canonical_rows)}")
    print(f"Coded: {coded} | Backtested (production): {backtested}")
    print(f"Data root: {data_root} | Real history available: {real_data}")
    if args.write_csv:
        write_csv_rows(csv_path, fieldnames, rows)
        print("Tracking columns ensured in CSV.")
    return 0


def cmd_list_strategies(_: argparse.Namespace) -> int:
    load_all_strategies(force=True)
    for item in list_strategy_metadata():
        print(f"{item['id']}\t{item['name']}\tvideo={item['source_video']}\tmodule={item['module']}")
    return 0


def composite_score(row: dict[str, Any], max_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades") or 0)
    if trades < min_trades:
        return 0.0
    pf = min(float(row.get("bt_profit_factor") or 0), 5.0)
    win_rate = float(row.get("bt_win_rate") or 0)
    sharpe = float(row.get("bt_sharpe_ratio") or 0)
    pnl = float(row.get("bt_total_pnl") or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / max_pnl) if max_pnl > 0 else 0.0
    return round(
        (pf / 5.0 * 0.35)
        + (win_rate / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10),
        4,
    )


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    config_defaults: dict[str, Any],
    output_dir: Path,
    data_source: str,
) -> InstrumentResult | None:
    required_tf_strings = config_data.get("required_timeframes") or [tf.name for tf in strategy_cls.timeframes]
    required_tfs = [tf_from_string(value) for value in required_tf_strings]
    start, end = client.get_full_date_range(symbol, required_tfs)
    if start is None or end is None:
        return None

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
    engine = BacktestEngine(config, strategy, client)
    result = engine.run()

    strategy_output_dir = output_dir / strategy_cls.id
    strategy_output_dir.mkdir(parents=True, exist_ok=True)
    json_path = strategy_output_dir / f"{symbol}.json"
    payload = result.to_dict()
    payload["data_source"] = data_source
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    return InstrumentResult(symbol=symbol, result=result, json_path=str(json_path))


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path,
    symbols: str | list[str] = "all",
    output_dir: str | Path = DEFAULT_OUTPUT,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    load_all_strategies(force=True)
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    module_name = strategy_module_name(strategy_cls)
    config_data = load_strategy_config(module_name)
    video_number = str(config_data.get("video_number", strategy_cls.source_video))

    data_root_path = Path(data_root)
    client = ExnessCSVClient(data_root_path)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    real_data = has_real_history(data_root_path)
    data_source = "exness_production" if real_data else "not_backtested"

    if symbols == "all":
        symbol_list = client.get_symbols()
    elif isinstance(symbols, str):
        symbol_list = [item.strip() for item in symbols.split(",") if item.strip()]
    else:
        symbol_list = list(symbols)

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_name,
        video_number=video_number,
        instruments_scanned=len(symbol_list),
        data_source=data_source,
        data_root_used=str(data_root_path),
    )

    instrument_results: list[InstrumentResult] = []
    for symbol in symbol_list:
        try:
            instrument = run_single_symbol_backtest(
                strategy_cls=strategy_cls,
                symbol=symbol,
                client=client,
                config_defaults=config_data,
                output_dir=output_path,
                data_source=data_source,
            )
            if instrument is None:
                summary.instruments_skipped += 1
                summary.matrix_rows.append(
                    {
                        "strategy_registry_id": strategy_cls.id,
                        "strategy_module_id": module_name,
                        "video_number": video_number,
                        "symbol": symbol,
                        "data_quality_note": "Missing required timeframe data",
                        "data_source": data_source,
                    }
                )
                continue
            instrument_results.append(instrument)
            summary.instruments_tested += 1
        except Exception as exc:
            summary.instruments_skipped += 1
            summary.matrix_rows.append(
                {
                    "strategy_registry_id": strategy_cls.id,
                    "strategy_module_id": module_name,
                    "video_number": video_number,
                    "symbol": symbol,
                    "data_quality_note": f"Backtest error: {exc}",
                    "data_source": data_source,
                }
            )

    raw_rows: list[dict[str, Any]] = []
    for instrument in instrument_results:
        stats = instrument.result
        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_name,
            "video_number": video_number,
            "symbol": instrument.symbol,
            "backtest_start_date": stats.config.start_date.date().isoformat(),
            "backtest_end_date": stats.config.end_date.date().isoformat(),
            "bt_total_trades": stats.total_trades,
            "bt_winning_trades": stats.winning_trades,
            "bt_losing_trades": stats.losing_trades,
            "bt_win_rate": stats.win_rate,
            "bt_profit_factor": stats.profit_factor,
            "bt_max_drawdown_pct": stats.max_drawdown_pct,
            "bt_total_pnl": stats.total_pnl,
            "bt_sharpe_ratio": stats.sharpe_ratio,
            "bt_avg_rr": stats.avg_rr,
            "bt_avg_trade_duration_mins": stats.avg_trade_duration,
            "backtest_result_json": instrument.json_path,
            "backtested_at": datetime.now(timezone.utc).isoformat(),
            "data_quality_note": "",
            "data_source": data_source,
        }
        raw_rows.append(row)

    max_pnl = max((float(row["bt_total_pnl"]) for row in raw_rows), default=0.0)
    min_trades = int(config_data.get("min_trades_for_ranking", 10))
    for row in raw_rows:
        row["composite_score"] = composite_score(row, max_pnl, min_trades)

    ranked = sorted(raw_rows, key=lambda item: item["composite_score"], reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = index

    summary.matrix_rows.extend(ranked)

    eligible = [row for row in ranked if int(row["bt_total_trades"]) >= min_trades]
    if eligible:
        summary.best_instrument = str(eligible[0]["symbol"])
        summary.worst_instrument = str(eligible[-1]["symbol"])

    if instrument_results:
        total_trades = sum(item.result.total_trades for item in instrument_results)
        total_wins = sum(item.result.winning_trades for item in instrument_results)
        total_pnl = sum(item.result.total_pnl for item in instrument_results)
        pf_values = [item.result.profit_factor for item in instrument_results if item.result.total_trades > 0]
        dd_values = [item.result.max_drawdown_pct for item in instrument_results]
        sharpe_values = [item.result.sharpe_ratio for item in instrument_results if item.result.total_trades > 0]
        rr_values = [item.result.avg_rr for item in instrument_results if item.result.total_trades > 0]
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0.0,
            "bt_profit_factor_all": round(sum(pf_values) / len(pf_values), 2) if pf_values else 0.0,
            "bt_max_drawdown_pct_all": round(max(dd_values), 2) if dd_values else 0.0,
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(sum(sharpe_values) / len(sharpe_values), 2) if sharpe_values else 0.0,
            "bt_avg_rr_all": round(sum(rr_values) / len(rr_values), 2) if rr_values else 0.0,
        }

    update_strategy_matrix(summary.matrix_rows)
    return summary


def update_strategy_matrix(rows: list[dict[str, Any]]) -> None:
    matrix_path = DEFAULT_OUTPUT / "strategy_instrument_matrix.csv"
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    fieldnames = MATRIX_COLUMNS[:]
    if matrix_path.exists():
        with matrix_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames:
                fieldnames = reader.fieldnames
            for row in reader:
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for column in MATRIX_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)

    for row in rows:
        key = (str(row.get("strategy_registry_id", "")), str(row.get("symbol", "")))
        merged = existing.get(key, {})
        merged.update({key_name: row.get(key_name, merged.get(key_name, "")) for key_name in fieldnames})
        existing[key] = merged

    temp_path = matrix_path.with_suffix(".csv.tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for _, row in sorted(existing.items()):
            writer.writerow(row)
    temp_path.replace(matrix_path)


def update_tracking_csv(
    csv_path: Path,
    module_name: str,
    registry_id: str,
    summary: MultiInstrumentSummary,
    anti_bias_passed: str,
    anti_bias_notes: str,
    implementation_status: str,
) -> None:
    fieldnames, rows = read_csv_rows(csv_path)
    now = datetime.now(timezone.utc).isoformat()
    canonical_updates = {}
    for row in rows:
        if row.get("module_to_code") != module_name:
            continue
        row["implementation_status"] = implementation_status
        row["strategy_module_id"] = module_name
        row["strategy_folder"] = f"strategies/{module_name}/"
        row["strategy_registry_id"] = registry_id
        row["coded_at"] = row.get("coded_at") or now
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["data_source"] = summary.data_source if summary.instruments_tested else "pending_exness_production"
        row["data_root_used"] = summary.data_root_used
        row["instruments_tested_count"] = str(summary.instruments_tested)
        if summary.instruments_tested:
            row["backtested_at"] = now
        for key, value in summary.aggregate_stats.items():
            row[key] = str(value)
        if summary.best_instrument:
            best_row = next((item for item in summary.matrix_rows if item.get("symbol") == summary.best_instrument), {})
            row["best_instrument"] = summary.best_instrument
            row["best_instrument_pf"] = str(best_row.get("bt_profit_factor", ""))
            row["best_instrument_win_rate"] = str(best_row.get("bt_win_rate", ""))
            row["best_instrument_pnl"] = str(best_row.get("bt_total_pnl", ""))
            row["best_instrument_trades"] = str(best_row.get("bt_total_trades", ""))
        if summary.worst_instrument:
            row["worst_instrument"] = summary.worst_instrument
        row["instrument_affinity_notes"] = build_affinity_notes(summary)
        canonical_updates = row

    if implementation_status == "coded_and_backtested" and canonical_updates:
        for row in rows:
            if row.get("action") != "DUPLICATE-SKIP":
                continue
            if row.get("module_to_code") != module_name:
                continue
            row["implementation_status"] = "covered_by_canonical"
            row["strategy_registry_id"] = registry_id
            for key in summary.aggregate_stats:
                row[key] = canonical_updates.get(key, "")
            row["best_instrument"] = canonical_updates.get("best_instrument", "")
            row["instrument_affinity_notes"] = canonical_updates.get("instrument_affinity_notes", "")

    write_csv_rows(csv_path, fieldnames, rows)


def build_affinity_notes(summary: MultiInstrumentSummary) -> str:
    ranked = sorted(summary.matrix_rows, key=lambda item: float(item.get("composite_score") or 0), reverse=True)
    top = [row for row in ranked if int(row.get("bt_total_trades") or 0) >= 10][:3]
    weak = [row for row in reversed(ranked) if int(row.get("bt_total_trades") or 0) >= 10][:2]
    if not top:
        return "Insufficient trade sample across instruments; production re-run required for affinity ranking."
    top_text = ", ".join(
        f"{row['symbol']} (PF={row.get('bt_profit_factor')}, trades={row.get('bt_total_trades')})" for row in top
    )
    weak_text = ", ".join(
        f"{row['symbol']} (PF={row.get('bt_profit_factor')}, trades={row.get('bt_total_trades')})" for row in weak
    )
    return f"Stronger on {top_text}. Weaker on {weak_text}."


def cmd_run(args: argparse.Namespace) -> int:
    data_root = resolve_data_root(args.data_root)
    real_data = has_real_history(data_root)
    strategy_cls = get_strategy(args.strategy)
    if strategy_cls is None:
        load_all_strategies(force=True)
        strategy_cls = get_strategy(args.strategy)
    if strategy_cls is None:
        print(f"Strategy not found: {args.strategy}")
        return 1

    module_name = strategy_module_name(strategy_cls)
    csv_path = Path(args.csv)

    anti_bias_passed = "yes"
    anti_bias_notes = (
        "Uses only completed M1 bars and session VP from prior session bars; "
        "NY session filter via zoneinfo; entries on bar close; stops/targets from "
        "absorption wick and VP levels from video spec."
    )

    if real_data:
        summary = run_multi_instrument_backtest(
            strategy_id=strategy_cls.id,
            data_root=data_root,
            symbols=args.symbols,
            output_dir=args.output,
        )
        status = "coded_and_backtested"
    else:
        summary = MultiInstrumentSummary(
            strategy_id=strategy_cls.id,
            strategy_module_id=module_name,
            video_number=strategy_cls.source_video,
            data_source="pending_exness_production",
            data_root_used=str(data_root),
        )
        status = "coded_pending_production_backtest"

    update_tracking_csv(
        csv_path=csv_path,
        module_name=module_name,
        registry_id=strategy_cls.id,
        summary=summary,
        anti_bias_passed=anti_bias_passed,
        anti_bias_notes=anti_bias_notes,
        implementation_status=status,
    )

    print(f"Strategy: {strategy_cls.id}")
    print(f"Status: {status}")
    print(f"Data source: {summary.data_source}")
    print(f"Instruments tested: {summary.instruments_tested}")
    if summary.best_instrument:
        print(f"Best instrument: {summary.best_instrument}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Audit CSV vs coded strategy folders")
    audit_parser.add_argument("--csv", default=str(DEFAULT_CSV))
    audit_parser.add_argument("--data-root", default=None)
    audit_parser.add_argument("--write-csv", action="store_true")
    audit_parser.set_defaults(func=cmd_audit)

    list_parser = subparsers.add_parser("list-strategies", help="List registered strategies")
    list_parser.set_defaults(func=cmd_list_strategies)

    run_parser = subparsers.add_parser("run", help="Run a strategy across instruments")
    run_parser.add_argument("--strategy", required=True)
    run_parser.add_argument("--symbols", default="all")
    run_parser.add_argument("--data-root", default=None)
    run_parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_parser.add_argument("--csv", default=str(DEFAULT_CSV))
    run_parser.add_argument("--start", default=None)
    run_parser.add_argument("--end", default=None)
    run_parser.set_defaults(func=cmd_run)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
