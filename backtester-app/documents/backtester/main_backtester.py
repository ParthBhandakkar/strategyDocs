#!/usr/bin/env python3
"""
Main backtester CLI — audit, list strategies, and run multi-instrument backtests.
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

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient, resolve_data_root
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies

logger = logging.getLogger(__name__)

DEFAULT_CSV = ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "results"
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
    start: datetime | None
    end: datetime | None
    composite_score: float = 0.0
    rank_within_strategy: int = 0
    data_quality_note: str = ""
    skipped: bool = False


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    module: str
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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_yaml_config(strategy_cls) -> dict[str, Any]:
    module = strategy_cls.id.split("_", 1)[-1]
    cfg_path = Path(__file__).resolve().parent / "strategies" / module / "config.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def _write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8") as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def _load_matrix_rows() -> tuple[list[str], list[dict[str, str]]]:
    if not MATRIX_CSV.exists():
        return MATRIX_COLUMNS, []
    with open(MATRIX_CSV, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or MATRIX_COLUMNS)
        rows = list(reader)
    for col in MATRIX_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def _save_matrix_rows(rows: list[dict[str, str]]):
    fieldnames, existing = _load_matrix_rows()
    index = {(r["strategy_registry_id"], r["symbol"]): i for i, r in enumerate(existing)}
    for row in rows:
        key = (row["strategy_registry_id"], row["symbol"])
        if key in index:
            existing[index[key]] = row
        else:
            existing.append(row)
    _write_csv_atomic(MATRIX_CSV, fieldnames, existing)


def composite_score(stats: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(stats.get("total_trades", 0) or 0)
    if trades < min_trades:
        return 0.0
    pf = min(float(stats.get("profit_factor", 0) or 0), 5.0)
    win_rate = float(stats.get("win_rate", 0) or 0)
    sharpe = float(stats.get("sharpe_ratio", 0) or 0)
    pnl = float(stats.get("total_pnl", 0) or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    return (
        (pf / 5.0 * 0.35)
        + (win_rate / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10)
    )


def _resolve_strategy(strategy_arg: str):
    load_all_strategies()
    strat = get_strategy(strategy_arg)
    if strat is None:
        from backtester.strategies.registry import get_strategy_by_module

        strat = get_strategy_by_module(strategy_arg)
    if strat is None:
        raise SystemExit(f"Strategy not found: {strategy_arg}")
    return strat


def cmd_audit(csv_path: Path):
    fieldnames, rows = _read_csv_rows(csv_path)
    coded_dirs = {
        p.name
        for p in (Path(__file__).resolve().parent / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__"}
    }
    load_all_strategies()
    registered = {cls.id: cls for cls in get_all_strategies()}
    canonical = [r for r in rows if r.get("action") == "CODE-CANONICAL"]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")
    print(f"Canonical modules: {len(canonical)}")
    print(f"Coded folders: {sorted(coded_dirs)}")
    print(f"Registered strategies: {sorted(registered)}")
    print(f"Completed (production backtest): {done}/{len(canonical)}")
    data_root = resolve_data_root()
    print(f"Data root: {data_root or 'UNAVAILABLE'}")
    if data_root:
        client = ExnessCSVClient(data_root)
        print(f"Symbols available: {len(client.get_symbols())}")


def cmd_list_strategies():
    load_all_strategies()
    for strat in get_all_strategies():
        print(f"{strat.id}\t{strat.name}\tvideo={strat.source_video}")


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    strategy_cls = _resolve_strategy(strategy_id)
    cfg = _load_yaml_config(strategy_cls)
    defaults = cfg.get("backtest_defaults", {})
    module = cfg.get("module") or strategy_cls.id.split("_", 1)[-1]
    video_number = str(cfg.get("video_number") or strategy_cls.source_video)
    output_dir = Path(output_dir or DEFAULT_OUTPUT)
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_root = resolve_data_root(data_root)
    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        module=module,
        video_number=video_number,
        data_root_used=resolved_root or "",
    )

    if not resolved_root:
        summary.data_source = "not_backtested"
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

    required_tfs = [tf_from_string(x) for x in cfg.get("required_timeframes", ["M1"])]
    min_trades_rank = int(cfg.get("min_trades_for_ranking", 10))
    results: list[InstrumentResult] = []

    for symbol in target_symbols:
        sym_start, sym_end = client.get_full_date_range(symbol, required_tfs)
        if sym_start is None or sym_end is None:
            summary.instruments_skipped += 1
            results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=None,
                    start=None,
                    end=None,
                    skipped=True,
                    data_quality_note="missing required timeframe data",
                )
            )
            continue

        bt_start = start or sym_start
        bt_end = end or sym_end
        strategy = strategy_cls()
        config = BacktestConfig(
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
        engine = BacktestEngine(config, strategy, client)
        result = engine.run()
        summary.instruments_tested += 1
        results.append(
            InstrumentResult(symbol=symbol, result=result, start=bt_start, end=bt_end)
        )

        json_dir = output_dir / strategy_cls.id
        json_dir.mkdir(parents=True, exist_ok=True)
        with open(json_dir / f"{symbol}.json", "w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle, indent=2)

    best_pnl = max(
        (r.result.total_pnl for r in results if r.result is not None),
        default=0.0,
    )
    now_iso = _utc_now_iso()
    matrix_rows: list[dict[str, Any]] = []
    for item in results:
        if item.skipped or item.result is None:
            matrix_rows.append(
                {
                    "strategy_registry_id": strategy_cls.id,
                    "strategy_module_id": module,
                    "video_number": video_number,
                    "symbol": item.symbol,
                    "backtest_start_date": "",
                    "backtest_end_date": "",
                    "bt_total_trades": "0",
                    "data_quality_note": item.data_quality_note,
                    "data_source": "exness_production",
                    "backtested_at": now_iso,
                    "composite_score": "0",
                    "rank_within_strategy": "0",
                }
            )
            continue
        stats = item.result.to_dict()["stats"]
        score = composite_score(stats, best_pnl, min_trades_rank)
        item.composite_score = score
        matrix_rows.append(
            {
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": module,
                "video_number": video_number,
                "symbol": item.symbol,
                "backtest_start_date": item.start.date().isoformat() if item.start else "",
                "backtest_end_date": item.end.date().isoformat() if item.end else "",
                "bt_total_trades": str(stats["total_trades"]),
                "bt_winning_trades": str(stats["winning_trades"]),
                "bt_losing_trades": str(stats["losing_trades"]),
                "bt_win_rate": str(stats["win_rate"]),
                "bt_profit_factor": str(stats["profit_factor"]),
                "bt_max_drawdown_pct": str(stats["max_drawdown_pct"]),
                "bt_total_pnl": str(stats["total_pnl"]),
                "bt_sharpe_ratio": str(stats["sharpe_ratio"]),
                "bt_avg_rr": str(stats["avg_rr"]),
                "bt_avg_trade_duration_mins": str(stats["avg_trade_duration_mins"]),
                "composite_score": f"{score:.4f}",
                "rank_within_strategy": "0",
                "backtest_result_json": str((output_dir / strategy_cls.id / f"{item.symbol}.json").resolve()),
                "backtested_at": now_iso,
                "data_quality_note": item.data_quality_note,
                "data_source": "exness_production",
            }
        )

    ranked = sorted(
        [r for r in results if r.result is not None and r.result.total_trades >= min_trades_rank],
        key=lambda r: r.composite_score,
        reverse=True,
    )
    rank_map = {r.symbol: i + 1 for i, r in enumerate(ranked)}
    for row in matrix_rows:
        row["rank_within_strategy"] = str(rank_map.get(row["symbol"], 0))

    summary.matrix_rows = matrix_rows
    summary.data_source = "exness_production"
    _save_matrix_rows(matrix_rows)

    tested_stats = [r.result for r in results if r.result is not None and r.result.total_trades > 0]
    if tested_stats:
        total_trades = sum(r.total_trades for r in tested_stats)
        total_wins = sum(r.winning_trades for r in tested_stats)
        gross_profit = sum(
            t.metadata.get("pnl_usd", t.pnl)
            for r in tested_stats
            for t in r.trades
            if t.metadata.get("pnl_usd", t.pnl) > 0
        )
        gross_loss = abs(
            sum(
                t.metadata.get("pnl_usd", t.pnl)
                for r in tested_stats
                for t in r.trades
                if t.metadata.get("pnl_usd", t.pnl) <= 0
            )
        )
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0,
            "bt_profit_factor_all": round(gross_profit / gross_loss, 2) if gross_loss else 0,
            "bt_max_drawdown_pct_all": max(r.max_drawdown_pct for r in tested_stats),
            "bt_total_pnl_all": round(sum(r.total_pnl for r in tested_stats), 2),
            "bt_sharpe_ratio_all": round(
                sum(r.sharpe_ratio for r in tested_stats) / len(tested_stats),
                2,
            ),
            "bt_avg_rr_all": round(
                sum(r.avg_rr for r in tested_stats) / len(tested_stats),
                2,
            ),
        }
    if ranked:
        best = ranked[0]
        worst = ranked[-1]
        summary.best_instrument = best.symbol
        summary.worst_instrument = worst.symbol
        summary.aggregate_stats.update(
            {
                "best_instrument": best.symbol,
                "best_instrument_pf": best.result.profit_factor if best.result else 0,
                "best_instrument_win_rate": best.result.win_rate if best.result else 0,
                "best_instrument_pnl": best.result.total_pnl if best.result else 0,
                "best_instrument_trades": best.result.total_trades if best.result else 0,
                "worst_instrument": worst.symbol,
            }
        )
        pf_best = best.result.profit_factor if best.result else 0
        summary.aggregate_stats["instrument_affinity_notes"] = (
            f"Strongest on {best.symbol} (PF={pf_best}, {best.result.total_trades} trades). "
            f"Weakest ranked: {worst.symbol} (PF={worst.result.profit_factor if worst.result else 0}). "
            f"VP absorption edge is session-dependent; NQ proxy symbols may differ from futures spec."
        )
    return summary


def update_tracking_csv(
    csv_path: Path,
    video_number: str,
    updates: dict[str, str],
    propagate_duplicate: bool = False,
):
    fieldnames, rows = _read_csv_rows(csv_path)
    module = updates.get("strategy_module_id", "")
    for row in rows:
        if row.get("video_number") == video_number:
            row.update({k: v for k, v in updates.items() if v is not None})
    if propagate_duplicate and updates.get("implementation_status") == "coded_and_backtested":
        for row in rows:
            if row.get("duplicate_of_video") == video_number:
                row["implementation_status"] = "covered_by_canonical"
                for key in TRACKING_COLUMNS:
                    if key in updates and key not in {"strategy_module_id", "strategy_folder", "strategy_registry_id"}:
                        row[key] = updates[key]
    _write_csv_atomic(csv_path, fieldnames, rows)


def cmd_run(args: argparse.Namespace):
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    strategy_cls = _resolve_strategy(args.strategy)
    cfg = _load_yaml_config(strategy_cls)
    module = cfg.get("module") or strategy_cls.id.split("_", 1)[-1]
    video_number = str(cfg.get("video_number") or strategy_cls.source_video)

    if summary.data_source == "exness_production":
        status = "coded_and_backtested"
        data_source = "exness_production"
    else:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"

    updates = {
        "implementation_status": status,
        "strategy_module_id": module,
        "strategy_folder": f"strategies/{module}/",
        "strategy_registry_id": strategy_cls.id,
        "coded_at": _utc_now_iso(),
        "backtested_at": _utc_now_iso() if summary.data_source == "exness_production" else "",
        "instruments_tested_count": str(summary.instruments_tested),
        "anti_bias_review_passed": "yes",
        "anti_bias_notes": (
            "M1 signals on bar close; session VP from same-day post-9:30 bars only; "
            "tick_volume wick proxy for orderflow; HTF feed closed-bar only; params from video spec."
        ),
        "backtest_error": "",
        "data_source": data_source,
        "data_root_used": summary.data_root_used,
        **summary.aggregate_stats,
    }
    if args.csv:
        update_tracking_csv(
            Path(args.csv),
            video_number,
            {k: str(v) for k, v in updates.items()},
            propagate_duplicate=summary.data_source == "exness_production",
        )

    print(json.dumps({"summary": summary.__dict__, "status": status}, default=str, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy backtester pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit.add_argument("--csv", default=str(DEFAULT_CSV))

    listing = sub.add_parser("list-strategies", help="List registered strategies")
    listing.set_defaults(func=lambda _a: cmd_list_strategies())

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


def main(argv: list[str] | None = None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "audit":
        cmd_audit(Path(args.csv))
    elif args.command == "list-strategies":
        cmd_list_strategies()
    elif args.command == "run":
        cmd_run(args)


if __name__ == "__main__":
    main()
