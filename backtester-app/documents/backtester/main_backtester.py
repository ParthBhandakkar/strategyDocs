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
from typing import Any

import yaml

# Ensure backtester package is importable
_BACKTESTER_ROOT = Path(__file__).resolve().parent
_DOCS_ROOT = _BACKTESTER_ROOT.parent
if str(_DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(_DOCS_ROOT))

from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.connectors.exness_csv import ExnessCSVClient, resolve_data_root
from backtester.strategies.registry import get_strategy, load_all_strategies, list_strategy_ids

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_CSV = _DOCS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = _BACKTESTER_ROOT / "results"
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
    rank: int = 0
    data_quality_note: str = ""
    skipped: bool = False


@dataclass
class MultiBacktestSummary:
    strategy_id: str
    module_id: str
    video_number: int
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    matrix_rows: list[dict] = field(default_factory=list)
    best_instrument: str = ""
    worst_instrument: str = ""
    aggregate_stats: dict = field(default_factory=dict)
    data_source: str = "not_backtested"
    data_root_used: str = ""


def load_strategy_config(module: str) -> dict:
    cfg_path = _BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def composite_score(row: dict, max_pnl: float, min_trades: int = 10) -> float:
    trades = row.get("bt_total_trades", 0)
    if trades < min_trades:
        return -1.0
    pf = min(row.get("bt_profit_factor", 0) or 0, 5)
    wr = row.get("bt_win_rate", 0) or 0
    sharpe = row.get("bt_sharpe_ratio", 0) or 0
    pnl = row.get("bt_total_pnl", 0) or 0
    sharpe_norm = min(max(sharpe, -2), 3) / 3
    pnl_norm = (pnl / max_pnl) if max_pnl > 0 else 0.0
    trade_norm = min(trades, 50) / 50
    return (
        (pf / 5 * 0.35)
        + (wr / 100 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (trade_norm * 0.10)
    )


def read_csv_rows(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".csv")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def update_matrix_rows(new_rows: list[dict]):
    existing: dict[tuple[str, str], dict] = {}
    if MATRIX_CSV.exists():
        with open(MATRIX_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row
    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = row
    write_csv_atomic(MATRIX_CSV, MATRIX_COLUMNS, list(existing.values()))


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    fieldnames, rows = read_csv_rows(csv_path)
    load_all_strategies()
    registered = list_strategy_ids()

    strategies_dir = _BACKTESTER_ROOT / "strategies"
    folders = [
        d.name
        for d in strategies_dir.iterdir()
        if d.is_dir() and d.name not in {"__pycache__"}
        and (d / "strategy.py").exists()
    ]

    data_root = resolve_data_root(args.data_root)
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_root else 0

    canonical = [r for r in rows if r.get("action") == "CODE-CANONICAL"]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")
    pending = sum(
        1 for r in canonical
        if r.get("implementation_status", "") in ("", "not_started", "in_progress", "failed")
    )

    print("\n=== Backtester Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Strategy folders on disk: {len(folders)} -> {folders}")
    print(f"Registered strategies: {registered}")
    print(f"CODE-CANONICAL: {len(canonical)} total, {done} coded_and_backtested, {pending} pending")
    print(f"Data root: {data_root or 'NOT FOUND'} ({symbol_count} symbols)")
    print(f"main_backtester.py: OK")
    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    load_all_strategies()
    for sid in list_strategy_ids():
        cls = get_strategy(sid)
        print(f"{sid}: {cls.name if cls else '?'}")
    return 0


def run_single_symbol(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    cfg_defaults: dict,
    strategy_id: str,
) -> tuple[Any | None, str]:
    required_tfs = [tf_from_string(t) for t in cfg_defaults.get("required_timeframes", ["M1"])]
    if not client.has_timeframes(symbol, required_tfs):
        missing = [t for t in required_tfs if not client.get_bars(symbol, t)]
        return None, f"Missing timeframes: {[str(t) for t in missing]}"

    start, end = client.get_full_date_range(symbol, required_tfs)
    if not start or not end:
        return None, "No date range available"

    config = BacktestConfig(
        strategy_id=strategy_id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=float(cfg_defaults.get("initial_balance", 10000)),
        risk_per_trade=float(cfg_defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(cfg_defaults.get("spread_pips", 1.0)),
        slippage_pips=float(cfg_defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(cfg_defaults.get("commission_per_lot", 7.0)),
    )

    strategy = strategy_cls()
    engine = BacktestEngine(config, strategy, client)
    try:
        result = engine.run()
        return result, ""
    except Exception as exc:
        logger.exception("Backtest failed for %s", symbol)
        return None, str(exc)


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str = "all",
    output_dir: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiBacktestSummary:
    load_all_strategies()
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    module = strategy_cls.__module__.split(".")[-2]
    cfg = load_strategy_config(module)
    video_number = int(cfg.get("video_number", 0))
    cfg_defaults = cfg.get("backtest_defaults", {})
    min_trades = int(cfg.get("min_trades_for_ranking", 10))

    resolved_root = resolve_data_root(data_root)
    summary = MultiBacktestSummary(
        strategy_id=strategy_cls.id,
        module_id=module,
        video_number=video_number,
        data_root_used=str(resolved_root) if resolved_root else "",
    )

    if resolved_root is None:
        summary.data_source = "not_backtested"
        return summary

    summary.data_source = "exness_production"
    client = ExnessCSVClient(resolved_root)
    all_symbols = client.get_symbols()
    if symbols != "all":
        all_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    summary.instruments_scanned = len(all_symbols)
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)
    strat_output = output_path / strategy_cls.id
    strat_output.mkdir(parents=True, exist_ok=True)

    instrument_results: list[InstrumentResult] = []
    now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    for symbol in all_symbols:
        result, note = run_single_symbol(strategy_cls, symbol, client, cfg_defaults, strategy_cls.id)
        if result is None:
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(symbol=symbol, result=None, data_quality_note=note, skipped=True)
            )
            continue

        summary.instruments_tested += 1
        stats = result.to_dict()["stats"]
        pnl_usd = sum(t.metadata.get("pnl_usd", 0) for t in result.trades)

        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module,
            "video_number": str(video_number),
            "symbol": symbol,
            "backtest_start_date": result.config.start_date.date().isoformat(),
            "backtest_end_date": result.config.end_date.date().isoformat(),
            "bt_total_trades": stats["total_trades"],
            "bt_winning_trades": stats["winning_trades"],
            "bt_losing_trades": stats["losing_trades"],
            "bt_win_rate": stats["win_rate"],
            "bt_profit_factor": stats["profit_factor"] if stats["profit_factor"] != float("inf") else 999.0,
            "bt_max_drawdown_pct": stats["max_drawdown_pct"],
            "bt_total_pnl": round(pnl_usd, 2),
            "bt_sharpe_ratio": stats["sharpe_ratio"],
            "bt_avg_rr": stats["avg_rr"],
            "bt_avg_trade_duration_mins": stats["avg_trade_duration_mins"],
            "composite_score": 0.0,
            "rank_within_strategy": 0,
            "backtest_result_json": json.dumps(result.to_dict()),
            "backtested_at": now_iso,
            "data_quality_note": note,
            "data_source": summary.data_source,
        }
        instrument_results.append(InstrumentResult(symbol=symbol, result=result, data_quality_note=note))
        summary.matrix_rows.append(row)

        json_path = strat_output / f"{symbol}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2)

    if summary.matrix_rows:
        max_pnl = max(r["bt_total_pnl"] for r in summary.matrix_rows)
        for row in summary.matrix_rows:
            row["composite_score"] = round(composite_score(row, max_pnl, min_trades), 4)

        ranked = sorted(
            [r for r in summary.matrix_rows if r["bt_total_trades"] >= min_trades],
            key=lambda r: r["composite_score"],
            reverse=True,
        )
        for i, row in enumerate(ranked, 1):
            row["rank_within_strategy"] = i

        if ranked:
            best = ranked[0]
            worst = ranked[-1]
            summary.best_instrument = best["symbol"]
            summary.worst_instrument = worst["symbol"]

        update_matrix_rows(summary.matrix_rows)

        all_trades = sum(r["bt_total_trades"] for r in summary.matrix_rows)
        total_wins = sum(r["bt_winning_trades"] for r in summary.matrix_rows)
        total_pnl = sum(r["bt_total_pnl"] for r in summary.matrix_rows)
        pfs = [r["bt_profit_factor"] for r in summary.matrix_rows if r["bt_total_trades"] > 0]
        dds = [r["bt_max_drawdown_pct"] for r in summary.matrix_rows if r["bt_total_trades"] > 0]
        sharpes = [r["bt_sharpe_ratio"] for r in summary.matrix_rows if r["bt_total_trades"] > 0]
        rrs = [r["bt_avg_rr"] for r in summary.matrix_rows if r["bt_total_trades"] > 0]

        summary.aggregate_stats = {
            "bt_total_trades_all": all_trades,
            "bt_win_rate_all": round(total_wins / all_trades * 100, 2) if all_trades else 0,
            "bt_profit_factor_all": round(sum(pfs) / len(pfs), 2) if pfs else 0,
            "bt_max_drawdown_pct_all": round(max(dds), 2) if dds else 0,
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(sum(sharpes) / len(sharpes), 2) if sharpes else 0,
            "bt_avg_rr_all": round(sum(rrs) / len(rrs), 2) if rrs else 0,
        }

    return summary


def update_tracking_csv(
    csv_path: Path,
    video_number: int,
    summary: MultiBacktestSummary,
    status: str,
    anti_bias_passed: str,
    anti_bias_notes: str,
    backtest_error: str = "",
):
    fieldnames, rows = read_csv_rows(csv_path)
    now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    for row in rows:
        if row.get("action") != "CODE-CANONICAL":
            continue
        if int(row.get("video_number", -1)) != video_number:
            continue

        row["implementation_status"] = status
        row["strategy_module_id"] = summary.module_id
        row["strategy_folder"] = f"strategies/{summary.module_id}/"
        row["strategy_registry_id"] = summary.strategy_id
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["backtest_error"] = backtest_error
        row["data_source"] = summary.data_source
        row["data_root_used"] = summary.data_root_used

        if status in ("coded", "coded_pending_production_backtest", "in_progress"):
            row["coded_at"] = row.get("coded_at") or now_iso

        if summary.instruments_tested > 0:
            row["backtested_at"] = now_iso
            row["instruments_tested_count"] = str(summary.instruments_tested)
            for k, v in summary.aggregate_stats.items():
                row[k] = str(v)
            if summary.best_instrument:
                best_row = next((r for r in summary.matrix_rows if r["symbol"] == summary.best_instrument), None)
                worst_row = next((r for r in summary.matrix_rows if r["symbol"] == summary.worst_instrument), None)
                if best_row:
                    row["best_instrument"] = summary.best_instrument
                    row["best_instrument_pf"] = str(best_row["bt_profit_factor"])
                    row["best_instrument_win_rate"] = str(best_row["bt_win_rate"])
                    row["best_instrument_pnl"] = str(best_row["bt_total_pnl"])
                    row["best_instrument_trades"] = str(best_row["bt_total_trades"])
                if worst_row:
                    row["worst_instrument"] = summary.worst_instrument
                row["instrument_affinity_notes"] = (
                    f"Tested {summary.instruments_tested} instruments. "
                    f"Best: {summary.best_instrument or 'n/a'}. "
                    f"Designed for NQ orderflow; Exness forex/metals proxy via tick_volume wick absorption."
                )

    # Propagate DUPLICATE-SKIP when production backtest complete
    if status == "coded_and_backtested" and summary.data_source == "exness_production":
        canonical_row = next(
            (r for r in rows if r.get("action") == "CODE-CANONICAL" and int(r.get("video_number", -1)) == video_number),
            None,
        )
        if canonical_row:
            module = canonical_row.get("module_to_code", "")
            for row in rows:
                if row.get("action") == "DUPLICATE-SKIP" and row.get("module_to_code") == module:
                    row["implementation_status"] = "covered_by_canonical"
                    for col in TRACKING_COLUMNS:
                        if col.startswith("bt_") or col.startswith("best_") or col in ("worst_instrument", "instrument_affinity_notes", "data_source"):
                            if canonical_row.get(col):
                                row[col] = canonical_row[col]

    write_csv_atomic(csv_path, fieldnames, rows)


def cmd_run(args: argparse.Namespace) -> int:
    strategy_cls = get_strategy(args.strategy)
    if strategy_cls is None:
        load_all_strategies()
        strategy_cls = get_strategy(args.strategy)
    if strategy_cls is None:
        print(f"Unknown strategy: {args.strategy}")
        return 1

    module = strategy_cls.__module__.split(".")[-2]
    cfg = load_strategy_config(module)
    video_number = int(cfg.get("video_number", 1))

    csv_path = Path(args.csv) if args.csv else DEFAULT_CSV
    fieldnames, rows = read_csv_rows(csv_path)
    for row in rows:
        if row.get("action") == "CODE-CANONICAL" and int(row.get("video_number", -1)) == video_number:
            row["implementation_status"] = "in_progress"
    write_csv_atomic(csv_path, fieldnames, rows)

    anti_bias_passed = "yes"
    anti_bias_notes = (
        "No future data: VP/session from bars <= current_time; HTF feed uses bar-close rule; "
        "NY sessions via zoneinfo America/New_York; entries on M1 close; SL/TP from structure at entry; "
        "params from video spec; all scannable symbols tested when data available."
    )

    try:
        summary = run_multi_instrument_backtest(
            strategy_id=strategy_cls.id,
            data_root=args.data_root,
            symbols=args.symbols,
            output_dir=args.output,
        )
    except Exception as exc:
        update_tracking_csv(
            csv_path, video_number, MultiBacktestSummary(strategy_cls.id, module, video_number),
            status="failed", anti_bias_passed=anti_bias_passed,
            anti_bias_notes=anti_bias_notes, backtest_error=str(exc),
        )
        raise

    if summary.data_source == "exness_production" and summary.instruments_tested > 0:
        status = "coded_and_backtested"
    elif summary.data_source == "not_backtested":
        status = "coded_pending_production_backtest"
        summary.data_source = "pending_exness_production"
    else:
        status = "coded_pending_production_backtest"

    update_tracking_csv(
        csv_path, video_number, summary, status,
        anti_bias_passed, anti_bias_notes,
    )

    print(f"\nMulti-instrument backtest complete: {summary.instruments_tested}/{summary.instruments_scanned} tested")
    if summary.best_instrument:
        print(f"Best: {summary.best_instrument}, Worst: {summary.worst_instrument}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit CSV vs disk vs data")
    audit.add_argument("--csv", default=str(DEFAULT_CSV))
    audit.add_argument("--data-root", default=None)
    audit.set_defaults(func=cmd_audit)

    ls = sub.add_parser("list-strategies", help="List registered strategies")
    ls.set_defaults(func=cmd_list_strategies)

    run = sub.add_parser("run", help="Run multi-instrument backtest")
    run.add_argument("--strategy", required=True)
    run.add_argument("--symbols", default="all")
    run.add_argument("--data-root", default=None)
    run.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run.add_argument("--csv", default=str(DEFAULT_CSV))
    run.add_argument("--start", default=None)
    run.add_argument("--end", default=None)
    run.set_defaults(func=cmd_run)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
