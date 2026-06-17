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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure backtester package is importable when run as script
_BACKTESTER_ROOT = Path(__file__).resolve().parent
_DOCS_ROOT = _BACKTESTER_ROOT.parent
if str(_DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(_DOCS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient, resolve_data_root
from backtester.core import BacktestConfig, BacktestResult
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies

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
    result: BacktestResult
    composite_score: float = 0.0
    rank: int = 0
    data_quality_note: str = ""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: Optional[str] = None
    worst_instrument: Optional[str] = None
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def _save_csv_rows(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    tmp = csv_path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(csv_path)


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    fieldnames, rows = _load_csv_rows(csv_path)

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")
    pending = sum(
        1 for r in canonical
        if r.get("implementation_status", "") in ("", "not_started", "in_progress", "failed")
    )

    strategies_dir = _BACKTESTER_ROOT / "strategies"
    folders = [
        d.name for d in strategies_dir.iterdir()
        if d.is_dir() and d.name not in {"__pycache__"} and (d / "strategy.py").exists()
    ]

    data_root = resolve_data_root(args.data_root)
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_root else 0

    print("=== Backtester Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Canonical modules: {len(canonical)} (done={done}, pending={pending})")
    print(f"Strategy folders on disk: {sorted(folders)}")
    print(f"Registered strategies: {[s.id for s in get_all_strategies()]}")
    print(f"Data root: {data_root or 'NOT FOUND'}")
    print(f"Symbols available: {symbol_count}")
    print(f"main_backtester.py: exists")
    print(f"core/: {(_BACKTESTER_ROOT / 'core').exists()}")
    print(f"connectors/exness_csv.py: {(_BACKTESTER_ROOT / 'connectors' / 'exness_csv.py').exists()}")

    # Persist any new tracking columns
    _save_csv_rows(csv_path, fieldnames, rows)
    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    for strat in get_all_strategies():
        print(f"{strat.id}\t{strat.name}\t{strat.source_video}")
    return 0


def _parse_symbols(client: ExnessCSVClient, symbols_arg: str) -> list[str]:
    if symbols_arg.lower() == "all":
        return client.get_symbols()
    return [s.strip().upper() for s in symbols_arg.split(",") if s.strip()]


def _required_timeframes(strategy_cls) -> list[TF]:
    return list(strategy_cls.timeframes)


def _load_strategy_config(strategy_cls) -> dict[str, Any]:
    module = strategy_cls.__module__.split(".")[-1]
    config_path = _BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
        with config_path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except ImportError:
        return {}


def _composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0))
    if trades < min_trades:
        return -1.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0)
    win_rate = float(row.get("bt_win_rate", 0) or 0)
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    sharpe_norm = min(max(sharpe, -2), 3) / 3
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    return (
        (pf / 5 * 0.35)
        + (win_rate / 100 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50 * 0.10)
    )


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path,
    symbols: str = "all",
    output_dir: str | Path = DEFAULT_OUTPUT,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> MultiInstrumentSummary:
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    client = ExnessCSVClient(data_root)
    symbol_list = _parse_symbols(client, symbols)
    config_yaml = _load_strategy_config(strategy_cls)
    defaults = config_yaml.get("backtest_defaults", {})
    module_id = config_yaml.get("module", strategy_cls.__module__.split(".")[-1])
    video_number = str(config_yaml.get("video_number", strategy_cls.source_video))

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    result_dir = output_path / strategy_cls.id
    result_dir.mkdir(parents=True, exist_ok=True)

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_id,
        video_number=video_number,
        data_source="exness_production",
        data_root_used=str(data_root),
    )

    instrument_results: list[InstrumentResult] = []
    required_tfs = _required_timeframes(strategy_cls)

    for symbol in symbol_list:
        missing = [tf for tf in required_tfs if not client.has_timeframe(symbol, tf)]
        if missing:
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=BacktestResult(config=BacktestConfig(
                        strategy_id=strategy_cls.id,
                        symbol=symbol,
                        start_date=datetime(2000, 1, 1),
                        end_date=datetime(2000, 1, 2),
                    )),
                    data_quality_note=f"missing_timeframes:{','.join(tf.name for tf in missing)}",
                )
            )
            continue

        sym_start, sym_end = client.get_full_date_range(symbol, required_tfs)
        if not sym_start or not sym_end:
            summary.instruments_skipped += 1
            continue

        bt_start = start or sym_start
        bt_end = end or sym_end

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
            instrument_results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=result,
                    start_date=bt_start,
                    end_date=bt_end,
                )
            )
            json_path = result_dir / f"{symbol}.json"
            with json_path.open("w", encoding="utf-8") as handle:
                json.dump(result.to_dict(), handle, indent=2)
        except Exception as exc:
            logger.error("Backtest failed for %s: %s", symbol, exc)
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=BacktestResult(config=bt_config),
                    data_quality_note=f"error:{exc}",
                )
            )

    rows_for_ranking: list[dict[str, Any]] = []
    for ir in instrument_results:
        if ir.data_quality_note:
            row = {
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": module_id,
                "video_number": video_number,
                "symbol": ir.symbol,
                "bt_total_trades": 0,
                "bt_total_pnl": 0,
                "data_quality_note": ir.data_quality_note,
                "data_source": summary.data_source,
            }
            summary.matrix_rows.append(row)
            continue

        r = ir.result
        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_id,
            "video_number": video_number,
            "symbol": ir.symbol,
            "backtest_start_date": ir.start_date.date().isoformat() if ir.start_date else "",
            "backtest_end_date": ir.end_date.date().isoformat() if ir.end_date else "",
            "bt_total_trades": r.total_trades,
            "bt_winning_trades": r.winning_trades,
            "bt_losing_trades": r.losing_trades,
            "bt_win_rate": r.win_rate,
            "bt_profit_factor": r.profit_factor,
            "bt_max_drawdown_pct": r.max_drawdown_pct,
            "bt_total_pnl": r.total_pnl,
            "bt_sharpe_ratio": r.sharpe_ratio,
            "bt_avg_rr": r.avg_rr,
            "bt_avg_trade_duration_mins": r.avg_trade_duration,
            "backtested_at": _utc_now_iso(),
            "data_quality_note": ir.data_quality_note,
            "data_source": summary.data_source,
            "backtest_result_json": str((result_dir / f"{ir.symbol}.json").resolve()),
        }
        rows_for_ranking.append(row)
        summary.matrix_rows.append(row)

    best_pnl = max((float(r["bt_total_pnl"]) for r in rows_for_ranking), default=0.0)
    for row in rows_for_ranking:
        row["composite_score"] = round(_composite_score(row, best_pnl), 4)

    ranked = sorted(rows_for_ranking, key=lambda r: r["composite_score"], reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = rank

    eligible = [r for r in ranked if int(r["bt_total_trades"]) >= 10]
    if eligible:
        summary.best_instrument = eligible[0]["symbol"]
        summary.worst_instrument = eligible[-1]["symbol"]

    if rows_for_ranking:
        total_trades = sum(int(r["bt_total_trades"]) for r in rows_for_ranking)
        total_wins = sum(int(r["bt_winning_trades"]) for r in rows_for_ranking)
        total_pnl = sum(float(r["bt_total_pnl"]) for r in rows_for_ranking)
        pf_vals = [float(r["bt_profit_factor"]) for r in rows_for_ranking if r["bt_total_trades"]]
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0,
            "bt_profit_factor_all": round(
                sum(pf_vals) / len(pf_vals), 2
            ) if pf_vals else 0,
            "bt_max_drawdown_pct_all": max(
                (float(r["bt_max_drawdown_pct"]) for r in rows_for_ranking), default=0
            ),
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(
                sum(float(r["bt_sharpe_ratio"]) for r in rows_for_ranking) / len(rows_for_ranking), 2
            ) if rows_for_ranking else 0,
            "bt_avg_rr_all": round(
                sum(float(r["bt_avg_rr"]) for r in rows_for_ranking) / len(rows_for_ranking), 2
            ) if rows_for_ranking else 0,
        }

    _update_matrix_csv(summary.matrix_rows)
    return summary


def _update_matrix_csv(new_rows: list[dict[str, Any]]):
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if MATRIX_CSV.exists():
        with MATRIX_CSV.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row

    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {col: str(row.get(col, "")) for col in MATRIX_COLUMNS}

    MATRIX_CSV.parent.mkdir(parents=True, exist_ok=True)
    with MATRIX_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in existing.values():
            writer.writerow(row)


def cmd_run(args: argparse.Namespace) -> int:
    data_root = resolve_data_root(args.data_root)
    if data_root is None:
        print("ERROR: No Exness history path found. Set --data-root or LOCAL_HISTORY_PATH.")
        return 1

    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )

    print("\n=== Backtest Summary ===")
    print(f"Strategy: {summary.strategy_id}")
    print(f"Tested: {summary.instruments_tested}, Skipped: {summary.instruments_skipped}")
    print(f"Best: {summary.best_instrument}, Worst: {summary.worst_instrument}")
    print(f"Aggregate: {summary.aggregate_stats}")
    return 0


def update_csv_for_strategy(
    csv_path: Path,
    summary: MultiInstrumentSummary,
    implementation_status: str,
    anti_bias_passed: str = "yes",
    anti_bias_notes: str = "",
    backtest_error: str = "",
):
    fieldnames, rows = _load_csv_rows(csv_path)
    now = _utc_now_iso()

    for row in rows:
        if row.get("module_to_code") != summary.strategy_module_id:
            continue
        if row.get("action") != "CODE-CANONICAL":
            continue

        row["implementation_status"] = implementation_status
        row["strategy_module_id"] = summary.strategy_module_id
        row["strategy_folder"] = f"strategies/{summary.strategy_module_id}/"
        row["strategy_registry_id"] = summary.strategy_id
        row["coded_at"] = row.get("coded_at") or now
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["backtest_error"] = backtest_error
        row["data_source"] = summary.data_source if implementation_status == "coded_and_backtested" else (
            "pending_exness_production" if implementation_status == "coded_pending_production_backtest" else "not_backtested"
        )
        row["data_root_used"] = summary.data_root_used
        row["instruments_tested_count"] = str(summary.instruments_tested)

        if implementation_status == "coded_and_backtested":
            row["backtested_at"] = now

        stats = summary.aggregate_stats
        for key, val in stats.items():
            row[key] = str(val)

        if summary.best_instrument:
            best_row = next(
                (r for r in summary.matrix_rows if r.get("symbol") == summary.best_instrument),
                {},
            )
            row["best_instrument"] = summary.best_instrument
            row["best_instrument_pf"] = str(best_row.get("bt_profit_factor", ""))
            row["best_instrument_win_rate"] = str(best_row.get("bt_win_rate", ""))
            row["best_instrument_pnl"] = str(best_row.get("bt_total_pnl", ""))
            row["best_instrument_trades"] = str(best_row.get("bt_total_trades", ""))

        if summary.worst_instrument:
            row["worst_instrument"] = summary.worst_instrument

        row["instrument_affinity_notes"] = _affinity_notes(summary)

    if implementation_status == "coded_and_backtested":
        for row in rows:
            if row.get("action") == "DUPLICATE-SKIP" and row.get("module_to_code") == summary.strategy_module_id:
                row["implementation_status"] = "covered_by_canonical"
                for key in TRACKING_COLUMNS:
                    if key in row and key in rows[0]:
                        canonical = next(
                            (r for r in rows if r.get("module_to_code") == summary.strategy_module_id and r.get("action") == "CODE-CANONICAL"),
                            None,
                        )
                        if canonical and key in canonical:
                            row[key] = canonical[key]

    _save_csv_rows(csv_path, fieldnames, rows)


def _affinity_notes(summary: MultiInstrumentSummary) -> str:
    ranked = sorted(
        [r for r in summary.matrix_rows if int(r.get("bt_total_trades", 0) or 0) >= 10],
        key=lambda r: float(r.get("composite_score", 0) or 0),
        reverse=True,
    )
    if not ranked:
        return "Insufficient trades across instruments; designed for NQ index futures — Exness FX/metals proxy."
    top = ranked[:2]
    bottom = ranked[-2:]
    top_str = ", ".join(f"{r['symbol']}(PF={r.get('bt_profit_factor')})" for r in top)
    bot_str = ", ".join(f"{r['symbol']}(PF={r.get('bt_profit_factor')})" for r in bottom)
    return f"Stronger on {top_str}. Weaker on {bot_str}. VP absorption edge is session/volume sensitive."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit CSV vs disk state")
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
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
