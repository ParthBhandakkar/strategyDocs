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

import yaml

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
MATRIX_CSV = DEFAULT_OUTPUT / "strategy_instrument_matrix.csv"

if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient, resolve_data_root
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

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
    stats: dict[str, Any]
    composite_score: float = 0.0
    rank: int = 0
    start_date: str = ""
    end_date: str = ""
    data_quality_note: str = ""
    json_path: str = ""


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    instrument_results: list[InstrumentResult] = field(default_factory=list)
    best_instrument: Optional[str] = None
    worst_instrument: Optional[str] = None
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def parse_required_timeframes(strategy_cls, config: dict[str, Any]) -> list[TF]:
    raw = config.get("required_timeframes") or [tf.name for tf in strategy_cls.timeframes]
    return [tf_from_string(item) if isinstance(item, str) else item for item in raw]


def compute_composite_score(stats: dict[str, Any], max_pnl: float, min_trades: int = 10) -> float:
    trades = stats.get("total_trades", 0)
    if trades < min_trades:
        return 0.0
    pf = min(float(stats.get("profit_factor", 0) or 0), 5.0)
    win_rate = float(stats.get("win_rate", 0) or 0)
    sharpe = float(stats.get("sharpe_ratio", 0) or 0)
    pnl = float(stats.get("total_pnl", 0) or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = pnl / max_pnl if max_pnl > 0 else 0.0
    pnl_norm = min(max(pnl_norm, 0.0), 1.0)
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
    required_tfs: list[TF],
    defaults: dict[str, Any],
    output_dir: Path,
) -> InstrumentResult | None:
    date_range = client.get_full_date_range(symbol, required_tfs)
    if not date_range:
        return InstrumentResult(
            symbol=symbol,
            stats={},
            data_quality_note="missing required timeframe data",
        )

    start_date, end_date = date_range
    config = BacktestConfig(
        strategy_id=strategy_cls.id,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_balance=float(defaults.get("initial_balance", 10000.0)),
        risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(defaults.get("spread_pips", 1.0)),
        slippage_pips=float(defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
    )

    strategy = strategy_cls()
    engine = BacktestEngine(config, strategy, client)
    result = engine.run()
    result_dict = result.to_dict()
    stats = result_dict["stats"]

    result_dir = output_dir / strategy_cls.id
    result_dir.mkdir(parents=True, exist_ok=True)
    json_path = result_dir / f"{symbol}.json"
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(result_dict, handle, indent=2)

    return InstrumentResult(
        symbol=symbol,
        stats=stats,
        start_date=start_date.date().isoformat(),
        end_date=end_date.date().isoformat(),
        json_path=str(json_path.relative_to(BACKTESTER_ROOT)),
    )


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> MultiInstrumentSummary:
    resolved_root = resolve_data_root(str(data_root) if data_root else None)
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module_id = strategy_cls.id.split("_", 1)[-1] if "_" in strategy_cls.id else strategy_cls.id
    config = load_strategy_config(module_id)
    defaults = config.get("backtest_defaults", {})
    required_tfs = parse_required_timeframes(strategy_cls, config)
    video_number = str(config.get("video_number", ""))

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        module_id=module_id,
        video_number=video_number,
        data_root_used=str(resolved_root) if resolved_root else "",
    )

    if resolved_root is None:
        summary.data_source = "not_backtested"
        return summary

    client = ExnessCSVClient(resolved_root)
    summary.data_source = "exness_production"
    all_symbols = client.get_symbols()
    summary.instruments_scanned = len(all_symbols)

    if isinstance(symbols, str):
        if symbols.lower() == "all":
            target_symbols = all_symbols
        else:
            target_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        target_symbols = [s.upper() for s in symbols]

    results: list[InstrumentResult] = []
    for symbol in target_symbols:
        if not client.has_timeframes(symbol, required_tfs):
            summary.instruments_skipped += 1
            results.append(
                InstrumentResult(
                    symbol=symbol,
                    stats={},
                    data_quality_note=f"missing timeframes: {[tf.name for tf in required_tfs]}",
                )
            )
            continue

        try:
            instrument_result = run_single_symbol_backtest(
                strategy_cls, symbol, client, required_tfs, defaults, output_path
            )
            if instrument_result:
                results.append(instrument_result)
                if instrument_result.stats:
                    summary.instruments_tested += 1
                else:
                    summary.instruments_skipped += 1
        except Exception as exc:
            summary.instruments_skipped += 1
            logger.exception("Backtest failed for %s: %s", symbol, exc)
            results.append(
                InstrumentResult(
                    symbol=symbol,
                    stats={},
                    data_quality_note=f"backtest error: {exc}",
                )
            )

    max_pnl = max(
        (float(r.stats.get("total_pnl", 0) or 0) for r in results if r.stats),
        default=0.0,
    )
    min_trades = int(config.get("min_trades_for_ranking", 10))

    ranked: list[InstrumentResult] = []
    for item in results:
        if item.stats:
            item.composite_score = compute_composite_score(item.stats, max_pnl, min_trades)
        ranked.append(item)

    ranked.sort(key=lambda r: r.composite_score, reverse=True)
    for idx, item in enumerate(ranked, start=1):
        item.rank = idx

    eligible = [r for r in ranked if r.stats and r.stats.get("total_trades", 0) >= min_trades]
    if eligible:
        summary.best_instrument = eligible[0].symbol
        summary.worst_instrument = eligible[-1].symbol

    now_iso = datetime.now(timezone.utc).isoformat()
    matrix_rows: list[dict[str, Any]] = []
    for item in ranked:
        stats = item.stats or {}
        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_id,
            "video_number": video_number,
            "symbol": item.symbol,
            "backtest_start_date": item.start_date,
            "backtest_end_date": item.end_date,
            "bt_total_trades": stats.get("total_trades", 0),
            "bt_winning_trades": stats.get("winning_trades", 0),
            "bt_losing_trades": stats.get("losing_trades", 0),
            "bt_win_rate": stats.get("win_rate", 0),
            "bt_profit_factor": stats.get("profit_factor", 0),
            "bt_max_drawdown_pct": stats.get("max_drawdown_pct", 0),
            "bt_total_pnl": stats.get("total_pnl", 0),
            "bt_sharpe_ratio": stats.get("sharpe_ratio", 0),
            "bt_avg_rr": stats.get("avg_rr", 0),
            "bt_avg_trade_duration_mins": stats.get("avg_trade_duration_mins", 0),
            "composite_score": item.composite_score,
            "rank_within_strategy": item.rank,
            "backtest_result_json": item.json_path,
            "backtested_at": now_iso if stats else "",
            "data_quality_note": item.data_quality_note,
            "data_source": summary.data_source if stats else "not_backtested",
        }
        matrix_rows.append(row)

    summary.matrix_rows = matrix_rows
    summary.instrument_results = ranked
    summary.aggregate_stats = _aggregate_stats(ranked)
    _update_matrix_csv(strategy_cls.id, matrix_rows)
    return summary


def _aggregate_stats(results: list[InstrumentResult]) -> dict[str, Any]:
    tested = [r for r in results if r.stats and r.stats.get("total_trades", 0) > 0]
    if not tested:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "total_pnl": 0.0,
            "sharpe_ratio": 0.0,
            "avg_rr": 0.0,
        }

    total_trades = sum(int(r.stats.get("total_trades", 0)) for r in tested)
    total_winners = sum(int(r.stats.get("winning_trades", 0)) for r in tested)
    total_pnl = sum(float(r.stats.get("total_pnl", 0) or 0) for r in tested)
    max_dd = max(float(r.stats.get("max_drawdown_pct", 0) or 0) for r in tested)
    gross_profit = sum(
        float(r.stats.get("total_pnl", 0) or 0)
        for r in tested
        if float(r.stats.get("total_pnl", 0) or 0) > 0
    )
    gross_loss = abs(
        sum(
            float(r.stats.get("total_pnl", 0) or 0)
            for r in tested
            if float(r.stats.get("total_pnl", 0) or 0) <= 0
        )
    )
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0
    avg_rr_values = [float(r.stats.get("avg_rr", 0) or 0) for r in tested if r.stats.get("total_trades")]
    sharpe_values = [float(r.stats.get("sharpe_ratio", 0) or 0) for r in tested]

    return {
        "total_trades": total_trades,
        "win_rate": round(total_winners / total_trades * 100, 2) if total_trades else 0.0,
        "profit_factor": pf,
        "max_drawdown_pct": round(max_dd, 2),
        "total_pnl": round(total_pnl, 2),
        "sharpe_ratio": round(sum(sharpe_values) / len(sharpe_values), 2) if sharpe_values else 0.0,
        "avg_rr": round(sum(avg_rr_values) / len(avg_rr_values), 2) if avg_rr_values else 0.0,
    }


def _update_matrix_csv(strategy_id: str, new_rows: list[dict[str, Any]]):
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    existing_rows: list[dict[str, Any]] = []
    if MATRIX_CSV.exists():
        with open(MATRIX_CSV, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row.get("strategy_registry_id") != strategy_id:
                    existing_rows.append(row)

    all_rows = existing_rows + new_rows
    with open(MATRIX_CSV, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)


def _ensure_csv_columns(csv_path: Path) -> list[str]:
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    changed = False
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
            changed = True

    if changed:
        for row in rows:
            for col in TRACKING_COLUMNS:
                row.setdefault(col, "")
        _write_csv_atomic(csv_path, fieldnames, rows)

    return fieldnames


def _write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8") as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        tmp_path = Path(tmp.name)
    tmp_path.replace(csv_path)


def cmd_audit(csv_path: Path):
    fieldnames = _ensure_csv_columns(csv_path)
    with open(csv_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    load_all_strategies()
    coded_modules = {
        folder.name
        for folder in (BACKTESTER_ROOT / "strategies").iterdir()
        if folder.is_dir() and folder.name not in {"__pycache__"}
        and (folder / "strategy.py").exists()
    }

    data_root = resolve_data_root()
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_root else 0

    print("\n=== Backtester Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Registered strategies: {len(get_all_strategies())}")
    print(f"Coded strategy folders: {sorted(coded_modules)}")
    print(f"Data root: {data_root or 'NOT AVAILABLE'}")
    print(f"Symbols available: {symbol_count}")
    print("\nCODE-CANONICAL status:")
    for row in rows:
        if row.get("action") != "CODE-CANONICAL":
            continue
        status = row.get("implementation_status") or "not_started"
        module = row.get("module_to_code", "")
        print(f"  Video {row.get('video_number')}: {module} -> {status}")


def cmd_list_strategies():
    strategies = get_all_strategies()
    print("\nRegistered strategies:")
    for cls in sorted(strategies, key=lambda c: c.id):
        print(f"  {cls.id}  {cls.name}  TFs={[tf.name for tf in cls.timeframes]}")


def cmd_run(args: argparse.Namespace):
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    print("\n=== Multi-Instrument Summary ===")
    print(f"Strategy: {summary.strategy_id}")
    print(f"Data root: {summary.data_root_used or 'unavailable'}")
    print(f"Scanned: {summary.instruments_scanned}, Tested: {summary.instruments_tested}, Skipped: {summary.instruments_skipped}")
    if summary.best_instrument:
        print(f"Best: {summary.best_instrument}")
    if summary.worst_instrument:
        print(f"Worst: {summary.worst_instrument}")
    print(f"Aggregate: {summary.aggregate_stats}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_parser = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit_parser.add_argument("--csv", default=str(DEFAULT_CSV))

    sub.add_parser("list-strategies", help="List registered strategies")

    run_parser = sub.add_parser("run", help="Run multi-instrument backtest")
    run_parser.add_argument("--strategy", required=True)
    run_parser.add_argument("--symbols", default="all")
    run_parser.add_argument("--data-root", default=None)
    run_parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_parser.add_argument("--start", default=None)
    run_parser.add_argument("--end", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "audit":
        cmd_audit(Path(args.csv))
        return 0
    if args.command == "list-strategies":
        cmd_list_strategies()
        return 0
    if args.command == "run":
        cmd_run(args)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
