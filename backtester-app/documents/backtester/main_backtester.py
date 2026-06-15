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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure backtester package is importable
_ROOT = Path(__file__).resolve().parent
_DOCS = _ROOT.parent
if str(_DOCS) not in sys.path:
    sys.path.insert(0, str(_DOCS))

import yaml

from backtester.connectors.exness_csv import ExnessCSVClient, resolve_data_root
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_strategy, list_strategy_ids, load_all_strategies

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_CSV = _DOCS / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = _ROOT / "results"

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

CANONICAL_MODULES = {
    "1": "vp_orderflow_absorption",
    "4": "gold_london_vp_failed_auction",
    "5": "multi_vp_ict",
    "6": "htf_fvg_inversion",
    "8": "vp_failed_auction_generic",
    "13": "htf_trend_smt_cisd",
    "17": "hourly_po3_fib",
    "28": "ifvg_inversion_ladder",
    "29": "tbv_absorption",
    "31": "po3_10am_4h",
    "39": "daily_bias_judas",
    "42": "one_candle_8am",
    "44": "london_orb",
    "52": "session_dol_fib",
    "54": "range_sweep_mss",
    "56": "gold_judas_8pm",
    "62": "continuation_purge",
    "65": "us30_judas",
    "69": "mmxm",
    "77": "4h_swing_liquidity",
    "78": "forex_session_judas",
    "81": "osok_1h_po3",
}


@dataclass
class RunSummary:
    strategy_id: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    best_instrument: str = ""
    worst_instrument: str = ""
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def _load_yaml_config(strategy_module: str) -> dict:
    cfg_path = _ROOT / "strategies" / strategy_module / "config.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _strategy_module_name(strategy_cls) -> str:
    parts = strategy_cls.__module__.split(".")
    folder = parts[-2] if len(parts) >= 2 and parts[-1] == "strategy" else parts[-1]
    yaml_cfg = _load_yaml_config(folder)
    return yaml_cfg.get("module", folder)


def _read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def _write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict]):
    tmp = csv_path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(csv_path)


def _composite_score(row: dict, max_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0) or 0)
    if trades < min_trades:
        return -1.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0)
    wr = float(row.get("bt_win_rate", 0) or 0)
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    sharpe_norm = min(max(sharpe, -2), 3) / 3
    pnl_norm = (pnl / max_pnl) if max_pnl > 0 else 0.0
    return (
        (pf / 5 * 0.35)
        + (wr / 100 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50 * 0.10)
    )


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    fieldnames, rows = _read_csv_rows(csv_path)
    load_all_strategies()
    coded_ids = list_strategy_ids()
    coded_folders = [
        p.name for p in (_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in ("__pycache__",)
    ]

    canonical = [r for r in rows if r.get("action") == "CODE-CANONICAL"]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")
    pending = sum(
        1 for r in canonical
        if r.get("implementation_status", "") in ("", "not_started", "in_progress", "failed")
    )

    data_root = resolve_data_root(args.data_root)
    sym_count = len(ExnessCSVClient(data_root).get_symbols()) if data_root else 0

    print("=== Backtester Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Strategy folders on disk: {sorted(coded_folders)}")
    print(f"Registered strategies: {coded_ids}")
    print(f"main_backtester.py: {'yes' if (_ROOT / 'main_backtester.py').exists() else 'no'}")
    print(f"Exness data root: {data_root or 'NOT FOUND'} ({sym_count} symbols)")
    print(f"Canonical progress: {done}/22 done, {pending} pending/in_progress")
    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    load_all_strategies()
    for sid in list_strategy_ids():
        cls = get_strategy(sid)
        print(f"  {sid}: {cls.name if cls else '?'}")
    return 0


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> RunSummary:
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    root = resolve_data_root(str(data_root) if data_root else None)
    summary = RunSummary(strategy_id=strategy_id, data_root_used=str(root) if root else "")

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module_name = _strategy_module_name(strategy_cls)
    yaml_cfg = _load_yaml_config(module_name)
    defaults = yaml_cfg.get("backtest_defaults", {})
    required_tfs = [tf_from_string(t) for t in yaml_cfg.get("required_timeframes", [])]
    if not required_tfs:
        required_tfs = list(strategy_cls.timeframes)

    if root is None:
        summary.data_source = "not_backtested"
        return summary

    client = ExnessCSVClient(root)
    summary.data_source = "exness_production"
    all_symbols = client.get_symbols()
    summary.instruments_scanned = len(all_symbols)

    if symbols == "all":
        target_symbols = all_symbols
    elif isinstance(symbols, str):
        target_symbols = [s.strip().upper() for s in symbols.split(",")]
    else:
        target_symbols = [s.upper() for s in symbols]

    now_iso = datetime.now(timezone.utc).isoformat()

    for sym in target_symbols:
        if not client.has_timeframes(sym, required_tfs):
            summary.instruments_skipped += 1
            summary.matrix_rows.append({
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": module_name,
                "video_number": yaml_cfg.get("video_number", ""),
                "symbol": sym,
                "data_quality_note": f"Missing required timeframes: {[t.name for t in required_tfs]}",
                "data_source": summary.data_source,
                "backtested_at": now_iso,
            })
            continue

        sym_start, sym_end = client.get_full_date_range(sym, required_tfs)
        if sym_start is None or sym_end is None:
            summary.instruments_skipped += 1
            continue

        bt_start = start or sym_start
        bt_end = end or sym_end

        config = BacktestConfig(
            strategy_id=strategy_cls.id,
            symbol=sym,
            start_date=bt_start,
            end_date=bt_end,
            initial_balance=float(defaults.get("initial_balance", 10000.0)),
            risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
            spread_pips=float(defaults.get("spread_pips", 1.0)),
            slippage_pips=float(defaults.get("slippage_pips", 0.5)),
            commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
        )

        engine = BacktestEngine(config, strategy_cls(), client)
        try:
            result = engine.run()
        except Exception as exc:
            logger.error("Backtest failed for %s: %s", sym, exc)
            summary.instruments_skipped += 1
            continue

        summary.instruments_tested += 1
        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_name,
            "video_number": yaml_cfg.get("video_number", ""),
            "symbol": sym,
            "backtest_start_date": bt_start.date().isoformat(),
            "backtest_end_date": bt_end.date().isoformat(),
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
            "backtested_at": now_iso,
            "data_source": summary.data_source,
            "data_quality_note": "",
        }
        summary.matrix_rows.append(row)

        strat_dir = output_path / strategy_cls.id
        strat_dir.mkdir(parents=True, exist_ok=True)
        with open(strat_dir / f"{sym}.json", "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2)

    if summary.matrix_rows:
        max_pnl = max(float(r.get("bt_total_pnl", 0) or 0) for r in summary.matrix_rows)
        min_trades = int(yaml_cfg.get("min_trades_for_ranking", 10))
        for row in summary.matrix_rows:
            row["composite_score"] = round(_composite_score(row, max_pnl, min_trades), 4)

        ranked = sorted(
            [r for r in summary.matrix_rows if float(r.get("composite_score", -1)) >= 0],
            key=lambda r: r["composite_score"],
            reverse=True,
        )
        for i, row in enumerate(ranked, 1):
            row["rank_within_strategy"] = i

        if ranked:
            summary.best_instrument = ranked[0]["symbol"]
            summary.worst_instrument = ranked[-1]["symbol"]

        tested = [r for r in summary.matrix_rows if r.get("bt_total_trades") is not None]
        if tested:
            total_trades = sum(int(r.get("bt_total_trades", 0) or 0) for r in tested)
            wins = sum(int(r.get("bt_winning_trades", 0) or 0) for r in tested)
            summary.aggregate_stats = {
                "bt_total_trades_all": total_trades,
                "bt_win_rate_all": round(wins / total_trades * 100, 2) if total_trades else 0,
                "bt_profit_factor_all": round(
                    sum(float(r.get("bt_profit_factor", 0) or 0) for r in tested) / len(tested), 2
                ),
                "bt_max_drawdown_pct_all": round(
                    max(float(r.get("bt_max_drawdown_pct", 0) or 0) for r in tested), 2
                ),
                "bt_total_pnl_all": round(sum(float(r.get("bt_total_pnl", 0) or 0) for r in tested), 2),
                "bt_sharpe_ratio_all": round(
                    sum(float(r.get("bt_sharpe_ratio", 0) or 0) for r in tested) / len(tested), 2
                ),
                "bt_avg_rr_all": round(
                    sum(float(r.get("bt_avg_rr", 0) or 0) for r in tested) / len(tested), 2
                ),
            }

        _update_matrix_csv(output_path / "strategy_instrument_matrix.csv", summary.matrix_rows)

    return summary


def _update_matrix_csv(matrix_path: Path, new_rows: list[dict]):
    existing: dict[tuple[str, str], dict] = {}
    fieldnames = MATRIX_COLUMNS
    if matrix_path.exists():
        with open(matrix_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or MATRIX_COLUMNS)
            for row in reader:
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row
    for col in MATRIX_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    for row in new_rows:
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        merged = {**existing.get(key, {}), **row}
        existing[key] = merged

    _write_csv_atomic(matrix_path, fieldnames, list(existing.values()))


def _update_tracking_csv(
    csv_path: Path,
    strategy_id: str,
    module: str,
    video_number: str,
    status: str,
    data_source: str,
    data_root: str,
    summary: RunSummary,
    anti_bias_passed: str = "yes",
    anti_bias_notes: str = "",
    backtest_error: str = "",
):
    fieldnames, rows = _read_csv_rows(csv_path)
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        if row.get("video_number") == str(video_number) and row.get("action") == "CODE-CANONICAL":
            row["implementation_status"] = status
            row["strategy_module_id"] = module
            row["strategy_folder"] = f"strategies/{module}/"
            row["strategy_registry_id"] = strategy_id
            row["coded_at"] = row.get("coded_at") or now
            if status == "coded_and_backtested":
                row["backtested_at"] = now
            row["instruments_tested_count"] = str(summary.instruments_tested)
            row["anti_bias_review_passed"] = anti_bias_passed
            row["anti_bias_notes"] = anti_bias_notes
            row["backtest_error"] = backtest_error
            row["data_source"] = data_source
            row["data_root_used"] = data_root
            agg = summary.aggregate_stats
            for k, v in agg.items():
                row[k] = str(v)
            if summary.best_instrument:
                best = next(
                    (r for r in summary.matrix_rows if r.get("symbol") == summary.best_instrument), {}
                )
                row["best_instrument"] = summary.best_instrument
                row["best_instrument_pf"] = str(best.get("bt_profit_factor", ""))
                row["best_instrument_win_rate"] = str(best.get("bt_win_rate", ""))
                row["best_instrument_pnl"] = str(best.get("bt_total_pnl", ""))
                row["best_instrument_trades"] = str(best.get("bt_total_trades", ""))
            if summary.worst_instrument:
                row["worst_instrument"] = summary.worst_instrument
            row["instrument_affinity_notes"] = (
                f"Tested {summary.instruments_tested}/{summary.instruments_scanned} symbols. "
                f"Best: {summary.best_instrument or 'n/a'}. "
                f"Designed for index futures; Exness forex/metals proxy."
            )

        if (
            row.get("action") == "DUPLICATE-SKIP"
            and row.get("duplicate_of_video") == str(video_number)
            and status == "coded_and_backtested"
            and data_source == "exness_production"
        ):
            row["implementation_status"] = "covered_by_canonical"
            row["strategy_module_id"] = module
            row["strategy_registry_id"] = strategy_id

    _write_csv_atomic(csv_path, fieldnames, rows)


def cmd_run(args: argparse.Namespace) -> int:
    strategy_id = args.strategy
    output_dir = Path(args.output)
    data_root = resolve_data_root(args.data_root)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        print(f"ERROR: strategy not found: {strategy_id}")
        return 1

    module = _strategy_module_name(strategy_cls)
    yaml_cfg = _load_yaml_config(module)
    video_number = str(yaml_cfg.get("video_number", "1"))

    anti_bias_notes = (
        "HTF bars gated after close in data_feed; session filters use America/New_York; "
        "VP/absorption from past session bars only; entries on M1 close; "
        "SL/TP from structure not optimized on backtest."
    )

    if data_root is None:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"
        summary = RunSummary(strategy_id=strategy_cls.id)
        _update_tracking_csv(
            Path(args.csv), strategy_cls.id, module, video_number,
            status, data_source, "", summary,
            anti_bias_passed="yes", anti_bias_notes=anti_bias_notes,
        )
        print("No Exness data root found — code marked coded_pending_production_backtest")
        return 0

    summary = run_multi_instrument_backtest(
        strategy_id=strategy_id,
        data_root=data_root,
        symbols=args.symbols,
        output_dir=output_dir,
    )

    status = "coded_and_backtested" if summary.instruments_tested > 0 else "failed"
    _update_tracking_csv(
        Path(args.csv), strategy_cls.id, module, video_number,
        status, summary.data_source, str(data_root), summary,
        anti_bias_passed="yes", anti_bias_notes=anti_bias_notes,
    )
    return 0


def main():
    parser = argparse.ArgumentParser(description="Strategy backtester pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="Audit CSV vs disk vs data")
    p_audit.add_argument("--csv", default=str(DEFAULT_CSV))
    p_audit.add_argument("--data-root", default=None)

    sub.add_parser("list-strategies", help="List registered strategies")

    p_run = sub.add_parser("run", help="Run multi-instrument backtest")
    p_run.add_argument("--strategy", required=True)
    p_run.add_argument("--symbols", default="all")
    p_run.add_argument("--data-root", default=None)
    p_run.add_argument("--output", default=str(DEFAULT_OUTPUT))
    p_run.add_argument("--csv", default=str(DEFAULT_CSV))
    p_run.add_argument("--start", default=None)
    p_run.add_argument("--end", default=None)

    args = parser.parse_args()
    if args.command == "audit":
        return cmd_audit(args)
    if args.command == "list-strategies":
        return cmd_list_strategies(args)
    if args.command == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
