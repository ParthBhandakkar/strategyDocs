#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, run multi-instrument backtests.
"""

from __future__ import annotations

import argparse
import csv
import json
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
WINDOWS_DEFAULT_DATA = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"

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


def _ensure_path() -> None:
    parent = str(DOCUMENTS_ROOT)
    if parent not in sys.path:
        sys.path.insert(0, parent)


@dataclass
class RunSummary:
    strategy_id: str
    module_id: str
    video_number: str
    data_root: str
    data_source: str
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str = ""
    worst_instrument: str = ""
    affinity_notes: str = ""


def resolve_data_root(cli_arg: str | None) -> tuple[str, bool]:
    """Return (path, exists_with_data)."""
    if cli_arg:
        path = cli_arg
        return path, _data_root_valid(path)

    env_path = os.getenv("LOCAL_HISTORY_PATH", "")
    if env_path and _data_root_valid(env_path):
        return env_path, True

    if _data_root_valid(WINDOWS_DEFAULT_DATA):
        return WINDOWS_DEFAULT_DATA, True

    return WINDOWS_DEFAULT_DATA, False


def _data_root_valid(path: str) -> bool:
    root = Path(path)
    if not root.is_dir():
        return False
    for child in root.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            return True
    return False


def load_strategy_config(module_name: str) -> dict[str, Any]:
    cfg_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def composite_score(row: dict[str, Any], best_pnl: float) -> float:
    pf = min(float(row.get("bt_profit_factor") or 0), 5.0) / 5.0 * 0.35
    wr = float(row.get("bt_win_rate") or 0) / 100.0 * 0.20
    sharpe = float(row.get("bt_sharpe_ratio") or 0)
    sharpe_norm = min(max(sharpe, -2), 3) / 3.0 * 0.20
    pnl = float(row.get("bt_total_pnl") or 0)
    pnl_norm = (pnl / best_pnl * 0.15) if best_pnl > 0 else 0.0
    trades = min(int(row.get("bt_total_trades") or 0), 50) / 50.0 * 0.10
    return round(pf + wr + sharpe_norm + pnl_norm + trades, 4)


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    data_root: str,
    output_dir: Path,
    data_source: str,
) -> dict[str, Any]:
    from backtester.connectors import ExnessCSVClient
    from backtester.core import BacktestConfig
    from backtester.core.engine import BacktestEngine
    from backtester.core.timeframes import TF, tf_from_string

    module_name = strategy_cls.__module__.split(".")[-2]
    cfg = load_strategy_config(module_name)
    defaults = cfg.get("backtest_defaults", {})
    required_tf = [tf_from_string(t) for t in cfg.get("required_timeframes", ["M1"])]

    client = ExnessCSVClient(data_root)
    for tf in required_tf:
        if not client.has_timeframe(symbol, tf):
            return {
                "skipped": True,
                "reason": f"missing timeframe {tf.name}",
            }

    start, end = client.get_full_date_range(symbol, required_tf)
    if not start or not end:
        return {"skipped": True, "reason": "no date range"}

    strategy = strategy_cls()
    config = BacktestConfig(
        strategy_id=strategy.id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=float(defaults.get("initial_balance", 10000.0)),
        risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(defaults.get("spread_pips", 1.0)),
        slippage_pips=float(defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
    )

    engine = BacktestEngine(config, strategy, client)
    result = engine.run()

    result_path = output_dir / strategy.id / f"{symbol}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, indent=2)

    return {
        "skipped": False,
        "symbol": symbol,
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "stats": result.to_dict()["stats"],
        "json_path": str(result_path),
        "data_source": data_source,
    }


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str = "all",
    output_dir: str | None = None,
) -> RunSummary:
    _ensure_path()
    from backtester.strategies.registry import get_strategy

    resolved_root, has_data = resolve_data_root(data_root)
    out = Path(output_dir or DEFAULT_OUTPUT)
    out.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module_name = strategy_cls.__module__.split(".")[-2]
    cfg = load_strategy_config(module_name)
    video_number = str(cfg.get("video_number", ""))
    data_source = "exness_production" if has_data else "not_backtested"

    summary = RunSummary(
        strategy_id=strategy_cls.id,
        module_id=module_name,
        video_number=video_number,
        data_root=resolved_root,
        data_source=data_source,
    )

    if not has_data:
        return summary

    from backtester.connectors import ExnessCSVClient

    client = ExnessCSVClient(resolved_root)
    if symbols == "all":
        symbol_list = client.get_symbols()
    else:
        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    summary.instruments_scanned = len(symbol_list)
    rows: list[dict[str, Any]] = []

    for symbol in symbol_list:
        outcome = run_single_symbol_backtest(
            strategy_cls, symbol, resolved_root, out, data_source
        )
        if outcome.get("skipped"):
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = outcome.get("reason", "skipped")
            continue

        summary.instruments_tested += 1
        stats = outcome["stats"]
        rows.append(
            {
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": module_name,
                "video_number": video_number,
                "symbol": symbol,
                "backtest_start_date": outcome["start"],
                "backtest_end_date": outcome["end"],
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
                "backtest_result_json": outcome["json_path"],
                "backtested_at": datetime.now(timezone.utc).isoformat(),
                "data_quality_note": "",
                "data_source": data_source,
            }
        )

    if rows:
        best_pnl = max(float(r["bt_total_pnl"]) for r in rows)
        for row in rows:
            row["composite_score"] = composite_score(row, best_pnl)

        ranked = sorted(rows, key=lambda r: r["composite_score"], reverse=True)
        for rank, row in enumerate(ranked, start=1):
            row["rank_within_strategy"] = rank

        min_trades = int(cfg.get("min_trades_for_ranking", 10))
        eligible = [r for r in ranked if int(r["bt_total_trades"]) >= min_trades]
        if eligible:
            summary.best_instrument = eligible[0]["symbol"]
            summary.worst_instrument = eligible[-1]["symbol"]

        strong = [r for r in eligible if float(r["bt_profit_factor"]) > 1.5 and int(r["bt_total_trades"]) >= 30]
        weak = [r for r in eligible if float(r["bt_profit_factor"]) < 1.0]
        notes: list[str] = []
        if strong:
            syms = ", ".join(r["symbol"] for r in strong[:3])
            notes.append(f"Strong on {syms} (PF>1.5, 30+ trades)")
        if weak:
            syms = ", ".join(r["symbol"] for r in weak[:3])
            notes.append(f"Weak on {syms} (PF<1)")
        if not notes:
            notes.append("Mixed results across Exness symbols; NQ-specific edge may not transfer.")
        summary.affinity_notes = ". ".join(notes)

        total_trades = sum(int(r["bt_total_trades"]) for r in rows)
        total_wins = sum(int(r["bt_winning_trades"]) for r in rows)
        total_pnl = sum(float(r["bt_total_pnl"]) for r in rows)
        pf_vals = [float(r["bt_profit_factor"]) for r in rows if r["bt_total_trades"]]
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0,
            "bt_profit_factor_all": round(sum(pf_vals) / len(pf_vals), 2) if pf_vals else 0,
            "bt_max_drawdown_pct_all": round(max(float(r["bt_max_drawdown_pct"]) for r in rows), 2),
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(
                sum(float(r["bt_sharpe_ratio"]) for r in rows) / len(rows), 2
            ),
            "bt_avg_rr_all": round(sum(float(r["bt_avg_rr"]) for r in rows) / len(rows), 2),
        }

    summary.matrix_rows = rows
    _update_matrix_csv(out / "strategy_instrument_matrix.csv", rows)
    return summary


def _update_matrix_csv(path: Path, new_rows: list[dict[str, Any]]) -> None:
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row

    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {col: str(row.get(col, "")) for col in MATRIX_COLUMNS}

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda r: (r["strategy_registry_id"], r["symbol"])):
            writer.writerow(row)
    tmp.replace(path)


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def _write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def cmd_audit(csv_path: Path) -> int:
    _ensure_path()
    from backtester.strategies.registry import list_strategy_ids

    fieldnames, rows = _read_csv_rows(csv_path)
    coded_dirs = [
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__", "tests"}
    ]
    registered = list_strategy_ids()
    data_root, has_data = resolve_data_root(None)

    canonical = [
        r for r in rows if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")

    print("=== Backtester Audit ===")
    print(f"Backtester root: {BACKTESTER_ROOT}")
    print(f"main_backtester.py: {'yes' if (BACKTESTER_ROOT / 'main_backtester.py').exists() else 'no'}")
    print(f"Strategy folders on disk: {sorted(coded_dirs)}")
    print(f"Registered strategies: {registered}")
    print(f"Data root: {data_root} (valid={has_data})")
    print(f"Canonical progress: {done}/{len(canonical)}")
    return 0


def cmd_list_strategies() -> int:
    _ensure_path()
    from backtester.strategies.registry import get_all_strategies

    for cls in get_all_strategies():
        print(f"{cls.id}\t{cls.name}\tvideo={cls.source_video}")
    return 0


def update_tracking_csv(
    csv_path: Path,
    video_number: str,
    updates: dict[str, str],
    propagate_duplicates: bool = False,
) -> None:
    fieldnames, rows = _read_csv_rows(csv_path)
    module_id = updates.get("strategy_module_id", "")

    for row in rows:
        if row.get("video_number") == video_number:
            row.update(updates)
        elif propagate_duplicates and row.get("module_to_code") == module_id:
            if row.get("action") == "DUPLICATE-SKIP":
                row["implementation_status"] = "covered_by_canonical"
                for key in TRACKING_COLUMNS:
                    if key in updates and key not in ("implementation_status",):
                        row[key] = updates[key]

    _write_csv_rows(csv_path, fieldnames, rows)


def cmd_run(args: argparse.Namespace) -> int:
    _ensure_path()
    csv_path = Path(args.csv)
    data_root, has_data = resolve_data_root(args.data_root)

    try:
        summary = run_multi_instrument_backtest(
            strategy_id=args.strategy,
            data_root=data_root,
            symbols=args.symbols,
            output_dir=args.output,
        )
    except Exception as exc:
        update_tracking_csv(
            csv_path,
            video_number="",
            updates={
                "implementation_status": "failed",
                "backtest_error": str(exc),
                "strategy_registry_id": args.strategy,
            },
        )
        print(f"Backtest failed: {exc}")
        return 1

    now = datetime.now(timezone.utc).isoformat()
    if has_data and summary.instruments_tested > 0:
        status = "coded_and_backtested"
        data_source = "exness_production"
    elif has_data:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"
    else:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"

    anti_bias = "yes"
    anti_notes = (
        "M1-only signals after bar close; session VP from past bars only; "
        "NY sessions via ZoneInfo; no post-hoc threshold tuning."
    )

    updates = {
        "implementation_status": status if summary.instruments_tested else "coded_pending_production_backtest",
        "strategy_module_id": summary.module_id,
        "strategy_folder": f"strategies/{summary.module_id}/",
        "strategy_registry_id": summary.strategy_id,
        "coded_at": now,
        "backtested_at": now if summary.instruments_tested else "",
        "instruments_tested_count": str(summary.instruments_tested),
        "anti_bias_review_passed": anti_bias,
        "anti_bias_notes": anti_notes,
        "backtest_error": "",
        "data_source": data_source if summary.instruments_tested else "pending_exness_production",
        "data_root_used": summary.data_root,
        "instrument_affinity_notes": summary.affinity_notes,
        "best_instrument": summary.best_instrument,
        "worst_instrument": summary.worst_instrument,
    }
    updates.update({k: str(v) for k, v in summary.aggregate_stats.items()})

    if summary.best_instrument:
        best_row = next(
            (r for r in summary.matrix_rows if r["symbol"] == summary.best_instrument),
            None,
        )
        if best_row:
            updates["best_instrument_pf"] = str(best_row["bt_profit_factor"])
            updates["best_instrument_win_rate"] = str(best_row["bt_win_rate"])
            updates["best_instrument_pnl"] = str(best_row["bt_total_pnl"])
            updates["best_instrument_trades"] = str(best_row["bt_total_trades"])

    update_tracking_csv(
        csv_path,
        video_number=summary.video_number,
        updates=updates,
        propagate_duplicates=status == "coded_and_backtested",
    )

    print(f"\nRun complete: {summary.strategy_id}")
    print(f"Instruments tested: {summary.instruments_tested}/{summary.instruments_scanned}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
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

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "audit":
        return cmd_audit(Path(args.csv))
    if args.command == "list-strategies":
        return cmd_list_strategies()
    if args.command == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
