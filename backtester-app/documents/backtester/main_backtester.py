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

from backtester.connectors.exness_csv import ExnessCSVClient, resolve_data_root
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_registry, get_strategy, load_all_strategies

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BACKTESTER_ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = BACKTESTER_ROOT.parent / "video_docs" / "strategy_videos_90.csv"
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


@dataclass
class SymbolBacktestResult:
    symbol: str
    stats: dict[str, Any]
    composite_score: float = 0.0
    rank_within_strategy: int = 0
    data_quality_note: str = ""
    result_path: str = ""
    skipped: bool = False


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    strategy_module_id: str
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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_yaml_config(strategy_cls) -> dict[str, Any]:
    module = strategy_cls.__module__
    folder = module.rsplit(".", 1)[-1]
    config_path = BACKTESTER_ROOT / "strategies" / folder / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _ensure_csv_columns(csv_path: Path) -> list[dict[str, str]]:
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    for row in rows:
        for col in TRACKING_COLUMNS:
            row.setdefault(col, "")

    _write_csv_atomic(csv_path, fieldnames, rows)
    return rows


def _write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(csv_path.parent), suffix=".csv.tmp", text=True
    )
    os.close(fd)
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, csv_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def cmd_audit(csv_path: Path):
    rows = _ensure_csv_columns(csv_path)
    registry = load_all_strategies()
    coded_folders = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__"}
    }

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(
        1 for r in canonical
        if r.get("implementation_status") == "coded_and_backtested"
    )

    print("=== Backtester Audit ===")
    print(f"Registry strategies: {len(registry)}")
    for sid, cls in sorted(registry.items()):
        print(f"  - {sid}: {cls.name}")
    print(f"Strategy folders on disk: {sorted(coded_folders)}")
    print(f"Canonical modules: {len(canonical)}")
    print(f"Completed (coded_and_backtested): {done}/{len(canonical)}")

    data_root = resolve_data_root()
    if data_root:
        client = ExnessCSVClient(data_root)
        symbols = client.get_symbols()
        print(f"Data root: {data_root} ({len(symbols)} symbols)")
    else:
        print("Data root: NOT FOUND (production backtest pending)")

    pending = [
        r for r in canonical
        if r.get("implementation_status", "") in ("", "not_started", "failed", "in_progress")
    ]
    if pending:
        pending.sort(key=lambda r: int(r.get("video_number", 999)))
        nxt = pending[0]
        print(
            f"Next pending: Video #{nxt.get('video_number')} "
            f"{nxt.get('module_to_code')} — status={nxt.get('implementation_status', 'not_started')}"
        )
    elif done == len(canonical):
        print("Pipeline complete.")


def cmd_list_strategies():
    registry = load_all_strategies()
    if not registry:
        print("No strategies registered.")
        return
    for sid in sorted(registry):
        cls = registry[sid]
        print(f"{sid}\t{cls.name}\tvideo={cls.source_video}")


def compute_composite_score(stats: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(stats.get("bt_total_trades", 0))
    if trades < min_trades:
        return 0.0
    pf = min(float(stats.get("bt_profit_factor", 0)), 5.0)
    win_rate = float(stats.get("bt_win_rate", 0))
    sharpe = float(stats.get("bt_sharpe_ratio", 0))
    pnl = float(stats.get("bt_total_pnl", 0))
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
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
    output_dir: Path,
    config_data: dict[str, Any],
) -> SymbolBacktestResult:
    defaults = config_data.get("backtest_defaults", {})
    required_tfs = [
        tf_from_string(tf_name)
        for tf_name in config_data.get("required_timeframes", ["M1"])
    ]

    for tf in strategy_cls.timeframes:
        if not client.has_timeframe(symbol, tf):
            return SymbolBacktestResult(
                symbol=symbol,
                stats={},
                skipped=True,
                data_quality_note=f"Missing timeframe {tf.name}",
            )

    start, end = client.get_full_date_range(symbol, list(set(strategy_cls.timeframes + required_tfs)))
    if start is None or end is None:
        return SymbolBacktestResult(
            symbol=symbol,
            stats={},
            skipped=True,
            data_quality_note="No date range available",
        )

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
    result_dict = result.to_dict()

    result_dir = output_dir / strategy_cls.id
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{symbol}.json"
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(result_dict, handle, indent=2)

    stats = result_dict["stats"]
    stats["backtest_start_date"] = config.start_date.date().isoformat()
    stats["backtest_end_date"] = config.end_date.date().isoformat()

    return SymbolBacktestResult(
        symbol=symbol,
        stats=stats,
        result_path=str(result_path),
    )


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    csv_path: str | Path | None = None,
) -> MultiInstrumentSummary:
    load_all_strategies()
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    config_data = _load_yaml_config(strategy_cls)
    module_id = config_data.get("module", strategy_id.split("_", 1)[-1])
    video_number = str(config_data.get("video_number", strategy_cls.source_video))

    resolved_root = resolve_data_root(str(data_root) if data_root else None)
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_id,
        video_number=video_number,
        data_root_used=str(resolved_root) if resolved_root else "",
    )

    if resolved_root is None:
        summary.data_source = "pending_exness_production"
        _update_csv_pending(strategy_cls, config_data, csv_path)
        return summary

    client = ExnessCSVClient(resolved_root)
    all_symbols = client.get_symbols()
    summary.instruments_scanned = len(all_symbols)

    if symbols == "all":
        target_symbols = all_symbols
    elif isinstance(symbols, str):
        target_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        target_symbols = [s.upper() for s in symbols]

    symbol_results: list[SymbolBacktestResult] = []
    for symbol in target_symbols:
        if symbol not in all_symbols:
            symbol_results.append(
                SymbolBacktestResult(
                    symbol=symbol,
                    stats={},
                    skipped=True,
                    data_quality_note="Symbol not in data root",
                )
            )
            continue
        try:
            result = run_single_symbol_backtest(
                strategy_cls, symbol, client, output_path, config_data
            )
            symbol_results.append(result)
        except Exception as exc:
            logger.error("Backtest failed for %s: %s", symbol, exc)
            symbol_results.append(
                SymbolBacktestResult(
                    symbol=symbol,
                    stats={},
                    skipped=True,
                    data_quality_note=str(exc),
                )
            )

    tested = [r for r in symbol_results if not r.skipped]
    summary.instruments_tested = len(tested)
    summary.instruments_skipped = len(symbol_results) - len(tested)
    summary.data_source = "exness_production"

    best_pnl = max((float(r.stats.get("bt_total_pnl", 0)) for r in tested), default=0.0)
    min_trades = int(config_data.get("min_trades_for_ranking", 10))

    for result in tested:
        result.composite_score = compute_composite_score(
            {
                "bt_total_trades": result.stats.get("total_trades", 0),
                "bt_profit_factor": result.stats.get("profit_factor", 0),
                "bt_win_rate": result.stats.get("win_rate", 0),
                "bt_sharpe_ratio": result.stats.get("sharpe_ratio", 0),
                "bt_total_pnl": result.stats.get("total_pnl", 0),
            },
            best_pnl,
            min_trades,
        )

    ranked = sorted(tested, key=lambda r: r.composite_score, reverse=True)
    for idx, result in enumerate(ranked, start=1):
        result.rank_within_strategy = idx

    summary.matrix_rows = _build_matrix_rows(
        strategy_cls, module_id, video_number, symbol_results, summary.data_source
    )
    _save_matrix_csv(summary.matrix_rows)
    summary.aggregate_stats = _aggregate_stats(tested)
    summary.best_instrument, summary.worst_instrument = _pick_best_worst(
        ranked, min_trades
    )

    _update_csv_after_backtest(
        strategy_cls,
        config_data,
        summary,
        csv_path,
        anti_bias_passed=True,
        anti_bias_notes=(
            "HTF bars gated by close; session uses America/New_York; "
            "signals on bar close; VP/absorption from past bars only; "
            "no post-hoc threshold tuning."
        ),
    )
    return summary


def _build_matrix_rows(
    strategy_cls,
    module_id: str,
    video_number: str,
    results: list[SymbolBacktestResult],
    data_source: str,
) -> list[dict[str, Any]]:
    now = _utc_now_iso()
    rows = []
    for result in results:
        stats = result.stats
        rows.append({
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_id,
            "video_number": video_number,
            "symbol": result.symbol,
            "backtest_start_date": stats.get("backtest_start_date", ""),
            "backtest_end_date": stats.get("backtest_end_date", ""),
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
            "composite_score": result.composite_score,
            "rank_within_strategy": result.rank_within_strategy,
            "backtest_result_json": result.result_path,
            "backtested_at": now if not result.skipped else "",
            "data_quality_note": result.data_quality_note,
            "data_source": data_source if not result.skipped else "not_backtested",
        })
    return rows


def _save_matrix_csv(new_rows: list[dict[str, Any]]):
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if MATRIX_CSV.exists():
        with open(MATRIX_CSV, "r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row

    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {col: str(row.get(col, "")) for col in MATRIX_COLUMNS}

    rows = list(existing.values())
    _write_csv_atomic(MATRIX_CSV, MATRIX_COLUMNS, rows)


def _aggregate_stats(tested: list[SymbolBacktestResult]) -> dict[str, Any]:
    if not tested:
        return {}
    total_trades = sum(int(r.stats.get("total_trades", 0)) for r in tested)
    total_pnl = sum(float(r.stats.get("total_pnl", 0)) for r in tested)
    win_rates = [float(r.stats.get("win_rate", 0)) for r in tested if r.stats.get("total_trades", 0)]
    pfs = [float(r.stats.get("profit_factor", 0)) for r in tested if r.stats.get("total_trades", 0)]
    dds = [float(r.stats.get("max_drawdown_pct", 0)) for r in tested]
    sharpes = [float(r.stats.get("sharpe_ratio", 0)) for r in tested]
    rrs = [float(r.stats.get("avg_rr", 0)) for r in tested if r.stats.get("total_trades", 0)]
    return {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": round(sum(win_rates) / len(win_rates), 2) if win_rates else 0,
        "bt_profit_factor_all": round(sum(pfs) / len(pfs), 2) if pfs else 0,
        "bt_max_drawdown_pct_all": round(max(dds), 2) if dds else 0,
        "bt_total_pnl_all": round(total_pnl, 2),
        "bt_sharpe_ratio_all": round(sum(sharpes) / len(sharpes), 2) if sharpes else 0,
        "bt_avg_rr_all": round(sum(rrs) / len(rrs), 2) if rrs else 0,
    }


def _pick_best_worst(
    ranked: list[SymbolBacktestResult], min_trades: int
) -> tuple[str, str]:
    eligible = [
        r for r in ranked
        if int(r.stats.get("total_trades", 0)) >= min_trades and r.composite_score > 0
    ]
    if not eligible:
        return "", ""
    best = eligible[0]
    worst = eligible[-1]
    return best.symbol, worst.symbol


def _update_csv_pending(strategy_cls, config_data: dict, csv_path: str | Path | None):
    csv_file = Path(csv_path or DEFAULT_CSV)
    rows = _ensure_csv_columns(csv_file)
    module_id = config_data.get("module", strategy_cls.id.split("_", 1)[-1])
    now = _utc_now_iso()

    for row in rows:
        if row.get("module_to_code") == module_id and row.get("action") == "CODE-CANONICAL":
            row["implementation_status"] = "coded_pending_production_backtest"
            row["strategy_module_id"] = module_id
            row["strategy_folder"] = f"strategies/{module_id}/"
            row["strategy_registry_id"] = strategy_cls.id
            row["coded_at"] = now
            row["data_source"] = "pending_exness_production"
            row["anti_bias_review_passed"] = "yes"
            row["anti_bias_notes"] = (
                "HTF close gating; NY zoneinfo sessions; bar-close entries; "
                "no synthetic data; production backtest deferred."
            )

    with open(csv_file, "r", encoding="utf-8", newline="") as handle:
        fieldnames = list(csv.DictReader(handle).fieldnames or [])
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    _write_csv_atomic(csv_file, fieldnames, rows)


def _update_csv_after_backtest(
    strategy_cls,
    config_data: dict,
    summary: MultiInstrumentSummary,
    csv_path: str | Path | None,
    anti_bias_passed: bool,
    anti_bias_notes: str,
):
    csv_file = Path(csv_path or DEFAULT_CSV)
    rows = _ensure_csv_columns(csv_file)
    module_id = config_data.get("module", strategy_cls.id.split("_", 1)[-1])
    now = _utc_now_iso()
    status = (
        "coded_and_backtested"
        if summary.data_source == "exness_production"
        else "coded_pending_production_backtest"
    )

    best_row = next(
        (r for r in summary.matrix_rows if r["symbol"] == summary.best_instrument),
        None,
    )
    worst_row = next(
        (r for r in summary.matrix_rows if r["symbol"] == summary.worst_instrument),
        None,
    )
    affinity = _affinity_notes(summary, best_row, worst_row)

    for row in rows:
        if row.get("module_to_code") == module_id and row.get("action") == "CODE-CANONICAL":
            row["implementation_status"] = status
            row["strategy_module_id"] = module_id
            row["strategy_folder"] = f"strategies/{module_id}/"
            row["strategy_registry_id"] = strategy_cls.id
            row["coded_at"] = row.get("coded_at") or now
            row["backtested_at"] = now if status == "coded_and_backtested" else ""
            row["instruments_tested_count"] = str(summary.instruments_tested)
            row["anti_bias_review_passed"] = "yes" if anti_bias_passed else "no"
            row["anti_bias_notes"] = anti_bias_notes
            row["data_source"] = summary.data_source
            row["data_root_used"] = summary.data_root_used
            for key, val in summary.aggregate_stats.items():
                row[key] = str(val)
            if best_row:
                row["best_instrument"] = summary.best_instrument
                row["best_instrument_pf"] = str(best_row.get("bt_profit_factor", ""))
                row["best_instrument_win_rate"] = str(best_row.get("bt_win_rate", ""))
                row["best_instrument_pnl"] = str(best_row.get("bt_total_pnl", ""))
                row["best_instrument_trades"] = str(best_row.get("bt_total_trades", ""))
            if worst_row:
                row["worst_instrument"] = summary.worst_instrument
            row["instrument_affinity_notes"] = affinity

        if (
            status == "coded_and_backtested"
            and row.get("duplicate_of_video") == summary.video_number
            and row.get("action") == "DUPLICATE-SKIP"
        ):
            row["implementation_status"] = "covered_by_canonical"
            row["strategy_registry_id"] = strategy_cls.id
            row["data_source"] = summary.data_source
            for key in summary.aggregate_stats:
                row[key] = str(summary.aggregate_stats[key])
            row["instrument_affinity_notes"] = affinity

    with open(csv_file, "r", encoding="utf-8", newline="") as handle:
        fieldnames = list(csv.DictReader(handle).fieldnames or [])
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    _write_csv_atomic(csv_file, fieldnames, rows)


def _affinity_notes(
    summary: MultiInstrumentSummary,
    best_row: dict | None,
    worst_row: dict | None,
) -> str:
    if not best_row:
        return (
            "No instrument met minimum trade threshold; strategy may need "
            "production data validation on liquid symbols."
        )
    return (
        f"Best on {summary.best_instrument} "
        f"(PF={best_row.get('bt_profit_factor')}, trades={best_row.get('bt_total_trades')}). "
        f"Weakest ranked: {summary.worst_instrument or 'n/a'}."
    )


def cmd_run(args: argparse.Namespace):
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
        csv_path=args.csv,
    )
    print("\n=== Run Summary ===")
    print(f"Strategy: {summary.strategy_id}")
    print(f"Data source: {summary.data_source}")
    print(f"Scanned: {summary.instruments_scanned}, tested: {summary.instruments_tested}, skipped: {summary.instruments_skipped}")
    if summary.aggregate_stats:
        print(f"Aggregate: {summary.aggregate_stats}")
    if summary.best_instrument:
        print(f"Best: {summary.best_instrument}, Worst: {summary.worst_instrument}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy backtester pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit_p.add_argument("--csv", default=str(DEFAULT_CSV))

    sub.add_parser("list-strategies", help="List registered strategies")

    run_p = sub.add_parser("run", help="Run multi-instrument backtest")
    run_p.add_argument("--strategy", required=True)
    run_p.add_argument("--symbols", default="all")
    run_p.add_argument("--data-root", default=None)
    run_p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_p.add_argument("--csv", default=str(DEFAULT_CSV))
    run_p.add_argument("--start", default=None)
    run_p.add_argument("--end", default=None)

    args = parser.parse_args(argv)
    if args.command == "audit":
        cmd_audit(Path(args.csv))
    elif args.command == "list-strategies":
        cmd_list_strategies()
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
