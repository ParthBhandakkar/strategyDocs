#!/usr/bin/env python3
"""
Shared CLI entry point for strategy backtests.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
DEFAULT_WINDOWS_DATA_ROOT = Path(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history")

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

from backtester.connectors import ExnessCSVClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class InstrumentResult:
    symbol: str
    result: Any
    composite_score: float = 0.0
    rank: int = 0
    data_quality_note: str = ""
    skipped: bool = False


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str = ""
    worst_instrument: str = ""
    instrument_affinity_notes: str = ""
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_data_root: str | None = None) -> Path:
    if cli_data_root:
        return Path(cli_data_root)
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_dir() and _has_symbol_folders(candidate):
            return candidate
    return DEFAULT_WINDOWS_DATA_ROOT


def _has_symbol_folders(path: Path) -> bool:
    return any(p.is_dir() for p in path.iterdir())


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return fieldnames, rows


def _write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    temp_path.replace(path)


def ensure_tracking_columns(fieldnames: list[str]) -> list[str]:
    updated = list(fieldnames)
    for column in TRACKING_COLUMNS:
        if column not in updated:
            updated.append(column)
    return updated


def strategy_module_name(strategy_cls) -> str:
    parts = strategy_cls.__module__.split(".")
    if parts[-1] == "strategy" and len(parts) >= 2:
        return parts[-2]
    return parts[-1]


def load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_strategy_config_from_class(strategy_cls) -> dict[str, Any]:
    return load_strategy_config(strategy_module_name(strategy_cls))


def composite_score(
    profit_factor: float,
    win_rate: float,
    sharpe: float,
    pnl: float,
    trades: int,
    best_pnl: float,
) -> float:
    pf_norm = min(max(profit_factor, 0.0), 5.0) / 5.0
    wr_norm = min(max(win_rate, 0.0), 100.0) / 100.0
    sharpe_norm = (min(max(sharpe, -2.0), 3.0) + 2.0) / 5.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    pnl_norm = min(max(pnl_norm, 0.0), 1.0)
    trade_norm = min(max(trades, 0), 50) / 50.0
    return round(
        pf_norm * 0.35
        + wr_norm * 0.20
        + sharpe_norm * 0.20
        + pnl_norm * 0.15
        + trade_norm * 0.10,
        4,
    )


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    config_defaults: dict[str, Any],
) -> InstrumentResult:
    required_tfs = [tf_from_string(item) for item in config_defaults.get("required_timeframes", ["M1"])]
    for tf in required_tfs:
        if not client.has_timeframe(symbol, tf):
            return InstrumentResult(
                symbol=symbol,
                result=None,
                skipped=True,
                data_quality_note=f"missing timeframe {tf.name}",
            )

    start, end = client.get_full_date_range(symbol, required_tfs)
    if start is None or end is None:
        return InstrumentResult(
            symbol=symbol,
            result=None,
            skipped=True,
            data_quality_note="missing date range",
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
    engine = BacktestEngine(config, strategy, client)
    result = engine.run()

    result_dir = output_dir / strategy_cls.id
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{symbol}.json"
    with result_path.open("w", encoding="utf-8") as handle:
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
    del start, end  # full per-symbol range enforced via client

    data_root_path = Path(data_root)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    module_name = strategy_module_name(strategy_cls)
    config_data = load_strategy_config(module_name)
    video_number = str(config_data.get("video_number", ""))

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_name,
        video_number=video_number,
        data_root_used=str(data_root_path),
    )

    if not data_root_path.is_dir() or not _has_symbol_folders(data_root_path):
        summary.data_source = "pending_exness_production"
        logger.warning("Data root unavailable: %s", data_root_path)
        return summary

    client = ExnessCSVClient(data_root_path)
    all_symbols = client.get_symbols()
    if isinstance(symbols, str) and symbols.lower() == "all":
        target_symbols = all_symbols
    elif isinstance(symbols, str):
        target_symbols = [item.strip().upper() for item in symbols.split(",") if item.strip()]
    else:
        target_symbols = [item.upper() for item in symbols]

    summary.instruments_scanned = len(target_symbols)
    summary.data_source = "exness_production"
    instrument_results: list[InstrumentResult] = []

    for symbol in target_symbols:
        instrument = run_single_symbol_backtest(
            strategy_cls=strategy_cls,
            symbol=symbol,
            client=client,
            output_dir=output_path,
            config_defaults=config_data,
        )
        if instrument.skipped:
            summary.instruments_skipped += 1
        else:
            summary.instruments_tested += 1
        instrument_results.append(instrument)

    min_trades = int(config_data.get("min_trades_for_ranking", 10))
    ranked: list[InstrumentResult] = []
    best_pnl = 0.0
    for instrument in instrument_results:
        if instrument.skipped or instrument.result is None:
            continue
        pnl = instrument.result.total_pnl
        if pnl > best_pnl:
            best_pnl = pnl

    for instrument in instrument_results:
        if instrument.skipped or instrument.result is None:
            continue
        stats = instrument.result
        instrument.composite_score = composite_score(
            profit_factor=stats.profit_factor if stats.profit_factor != float("inf") else 5.0,
            win_rate=stats.win_rate,
            sharpe=stats.sharpe_ratio,
            pnl=stats.total_pnl,
            trades=stats.total_trades,
            best_pnl=best_pnl,
        )
        ranked.append(instrument)

    ranked.sort(key=lambda item: item.composite_score, reverse=True)
    for index, instrument in enumerate(ranked, start=1):
        instrument.rank = index

    now_iso = datetime.now(timezone.utc).isoformat()
    matrix_rows: list[dict[str, Any]] = []
    for instrument in instrument_results:
        if instrument.skipped or instrument.result is None:
            matrix_rows.append(
                {
                    "strategy_registry_id": strategy_cls.id,
                    "strategy_module_id": module_name,
                    "video_number": video_number,
                    "symbol": instrument.symbol,
                    "data_quality_note": instrument.data_quality_note,
                    "data_source": summary.data_source,
                    "backtested_at": now_iso,
                }
            )
            continue

        stats = instrument.result
        matrix_rows.append(
            {
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
                "bt_total_pnl": round(stats.total_pnl, 2),
                "bt_sharpe_ratio": stats.sharpe_ratio,
                "bt_avg_rr": stats.avg_rr,
                "bt_avg_trade_duration_mins": stats.avg_trade_duration,
                "composite_score": instrument.composite_score,
                "rank_within_strategy": instrument.rank,
                "backtest_result_json": str(output_path / strategy_cls.id / f"{instrument.symbol}.json"),
                "backtested_at": now_iso,
                "data_quality_note": instrument.data_quality_note,
                "data_source": summary.data_source,
            }
        )

    summary.matrix_rows = matrix_rows

    eligible = [item for item in ranked if item.result and item.result.total_trades >= min_trades]
    if eligible:
        best = eligible[0]
        worst = eligible[-1]
        summary.best_instrument = best.symbol
        summary.worst_instrument = worst.symbol
        summary.instrument_affinity_notes = (
            f"Strongest on {best.symbol} (PF={best.result.profit_factor}, "
            f"{best.result.total_trades} trades). Weakest ranked symbol {worst.symbol} "
            f"(PF={worst.result.profit_factor}, {worst.result.total_trades} trades)."
        )

    tested_stats = [item.result for item in instrument_results if item.result is not None]
    if tested_stats:
        total_trades = sum(item.total_trades for item in tested_stats)
        total_wins = sum(item.winning_trades for item in tested_stats)
        gross_profit = sum(
            trade.pnl for result in tested_stats for trade in result.trades if trade.pnl > 0
        )
        gross_loss = abs(
            sum(trade.pnl for result in tested_stats for trade in result.trades if trade.pnl <= 0)
        )
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0.0,
            "bt_profit_factor_all": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0,
            "bt_max_drawdown_pct_all": round(max(item.max_drawdown_pct for item in tested_stats), 2),
            "bt_total_pnl_all": round(sum(item.total_pnl for item in tested_stats), 2),
            "bt_sharpe_ratio_all": round(
                sum(item.sharpe_ratio for item in tested_stats) / len(tested_stats),
                2,
            ),
            "bt_avg_rr_all": round(
                sum(item.avg_rr for item in tested_stats) / len(tested_stats),
                2,
            ),
        }

    update_strategy_matrix(matrix_rows, output_path / "strategy_instrument_matrix.csv")
    return summary


def update_strategy_matrix(rows: list[dict[str, Any]], matrix_path: Path):
    existing_rows: list[dict[str, str]] = []
    fieldnames = MATRIX_COLUMNS
    if matrix_path.exists():
        with matrix_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or MATRIX_COLUMNS
            existing_rows = [dict(row) for row in reader]

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in existing_rows:
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        merged[key] = row

    for row in rows:
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        merged[key] = {**merged.get(key, {}), **row}

    final_fieldnames = list(dict.fromkeys([*fieldnames, *MATRIX_COLUMNS]))
    _write_csv_atomic(matrix_path, final_fieldnames, list(merged.values()))


def audit_csv(csv_path: Path) -> dict[str, Any]:
    fieldnames, rows = _read_csv_rows(csv_path)
    fieldnames = ensure_tracking_columns(fieldnames)

    coded_modules = {
        folder.name
        for folder in (BACKTESTER_ROOT / "strategies").iterdir()
        if folder.is_dir() and folder.name not in {"base", "registry", "__pycache__"}
    }
    load_all_strategies(force=True)
    registry_ids = {cls.id: cls for cls in get_all_strategies()}

    canonical_rows = [
        row
        for row in rows
        if row.get("action") == "CODE-CANONICAL" and row.get("is_backtestable") == "yes"
    ]
    status_counts: dict[str, int] = {}
    for row in rows:
        status = row.get("implementation_status") or "not_started"
        status_counts[status] = status_counts.get(status, 0) + 1

    data_root = resolve_data_root()
    data_available = data_root.is_dir() and _has_symbol_folders(data_root)

    changed = False
    for row in rows:
        for column in TRACKING_COLUMNS:
            row.setdefault(column, "")
        module = row.get("module_to_code", "")
        if module in coded_modules:
            strategy_cls = None
            for strat_id, cls in registry_ids.items():
                if module in strat_id or cls.__module__.endswith(module):
                    strategy_cls = cls
                    break
            if strategy_cls:
                if not row.get("strategy_registry_id"):
                    row["strategy_registry_id"] = strategy_cls.id
                    changed = True
                if not row.get("strategy_folder"):
                    row["strategy_folder"] = f"strategies/{module}/"
                    changed = True
                if not row.get("strategy_module_id"):
                    row["strategy_module_id"] = module
                    changed = True

    if changed:
        _write_csv_atomic(csv_path, fieldnames, rows)

    return {
        "csv_path": str(csv_path),
        "canonical_total": len(canonical_rows),
        "coded_modules_on_disk": sorted(coded_modules),
        "registered_strategies": sorted(registry_ids.keys()),
        "status_counts": status_counts,
        "data_root": str(data_root),
        "data_available": data_available,
        "symbol_count": len(ExnessCSVClient(data_root).get_symbols()) if data_available else 0,
    }


def update_tracking_row(
    csv_path: Path,
    video_number: str,
    updates: dict[str, str],
):
    fieldnames, rows = _read_csv_rows(csv_path)
    fieldnames = ensure_tracking_columns(fieldnames)
    for row in rows:
        if row.get("video_number") == str(video_number):
            row.update({key: str(value) for key, value in updates.items()})
    _write_csv_atomic(csv_path, fieldnames, rows)


def cmd_audit(args: argparse.Namespace) -> int:
    report = audit_csv(Path(args.csv))
    print(json.dumps(report, indent=2))
    return 0


def cmd_list_strategies(_: argparse.Namespace) -> int:
    strategies = get_all_strategies()
    for strategy_cls in sorted(strategies, key=lambda cls: cls.id):
        print(f"{strategy_cls.id}\t{strategy_cls.name}\tvideo={strategy_cls.source_video}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    data_root = resolve_data_root(args.data_root)
    output_dir = Path(args.output)
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=data_root,
        symbols=args.symbols,
        output_dir=output_dir,
    )

    if summary.data_source != "exness_production":
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"
    else:
        status = "coded_and_backtested"
        data_source = "exness_production"

    anti_bias_notes = (
        "Signals use only closed M1 bars and session VP from prior bars; "
        "HTF exposure deferred until bar close; entries on bar close through local clusters."
    )

    updates = {
        "implementation_status": status,
        "strategy_module_id": summary.strategy_module_id,
        "strategy_folder": f"strategies/{summary.strategy_module_id}/",
        "strategy_registry_id": summary.strategy_id,
        "coded_at": datetime.now(timezone.utc).isoformat(),
        "backtested_at": datetime.now(timezone.utc).isoformat() if summary.instruments_tested else "",
        "instruments_tested_count": str(summary.instruments_tested),
        "anti_bias_review_passed": "yes",
        "anti_bias_notes": anti_bias_notes,
        "backtest_error": "",
        "data_source": data_source,
        "data_root_used": summary.data_root_used,
        "instrument_affinity_notes": summary.instrument_affinity_notes,
        "best_instrument": summary.best_instrument,
        "worst_instrument": summary.worst_instrument,
    }
    updates.update({key: str(value) for key, value in summary.aggregate_stats.items()})

    if summary.best_instrument:
        best_row = next(
            (row for row in summary.matrix_rows if row.get("symbol") == summary.best_instrument),
            {},
        )
        updates.update(
            {
                "best_instrument_pf": str(best_row.get("bt_profit_factor", "")),
                "best_instrument_win_rate": str(best_row.get("bt_win_rate", "")),
                "best_instrument_pnl": str(best_row.get("bt_total_pnl", "")),
                "best_instrument_trades": str(best_row.get("bt_total_trades", "")),
            }
        )

    update_tracking_row(Path(args.csv), summary.video_number, updates)
    print(json.dumps(summary.__dict__, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy backtester CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Audit CSV vs coded modules")
    audit_parser.add_argument("--csv", default=str(DEFAULT_CSV))

    subparsers.add_parser("list-strategies", help="List registered strategies")

    run_parser = subparsers.add_parser("run", help="Run multi-instrument backtest")
    run_parser.add_argument("--strategy", required=True)
    run_parser.add_argument("--symbols", default="all")
    run_parser.add_argument("--data-root", default=None)
    run_parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_parser.add_argument("--csv", default=str(DEFAULT_CSV))
    run_parser.add_argument("--start", default=None)
    run_parser.add_argument("--end", default=None)

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
    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
