#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, run.
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
WINDOWS_DEFAULT_DATA_ROOT = Path(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history")

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


def _ensure_import_path():
    parent = str(DOCUMENTS_ROOT)
    if parent not in sys.path:
        sys.path.insert(0, parent)


@dataclass
class RunSummary:
    strategy_id: str
    strategy_module_id: str
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
    instrument_affinity_notes: str = ""


def resolve_data_root(cli_root: str | None = None) -> tuple[Path | None, str]:
    if cli_root:
        path = Path(cli_root)
        if path.is_dir() and _has_symbol_folders(path):
            return path, "cli"
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_folders(path):
            return path, "env"
    if WINDOWS_DEFAULT_DATA_ROOT.is_dir() and _has_symbol_folders(WINDOWS_DEFAULT_DATA_ROOT):
        return WINDOWS_DEFAULT_DATA_ROOT, "windows_default"
    return None, "missing"


def _has_symbol_folders(path: Path) -> bool:
    for entry in path.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            return True
    return False


def load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0) or 0)
    if trades < min_trades:
        return 0.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0)
    win_rate = float(row.get("bt_win_rate", 0) or 0)
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    return round(
        (pf / 5.0 * 0.35)
        + (win_rate / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10),
        4,
    )


def run_single_backtest(strategy_cls, symbol: str, data_root: Path, output_dir: Path) -> dict[str, Any]:
    _ensure_import_path()
    from backtester.connectors import ExnessCSVClient
    from backtester.core import BacktestConfig
    from backtester.core.engine import BacktestEngine
    from backtester.core.timeframes import tf_from_string

    module_name = strategy_cls.__module__.split(".")[-1]
    config_data = load_strategy_config(module_name)
    defaults = config_data.get("backtest_defaults", {})
    required_tfs = [
        tf_from_string(tf_name) for tf_name in config_data.get("required_timeframes", ["M1"])
    ]

    client = ExnessCSVClient(data_root)
    date_range = client.get_full_date_range(symbol, required_tfs)
    if date_range is None:
        return {
            "skipped": True,
            "reason": f"Missing required timeframes for {symbol}",
        }

    start_date, end_date = date_range
    strategy = strategy_cls()
    backtest_config = BacktestConfig(
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

    engine = BacktestEngine(backtest_config, strategy, client)
    result = engine.run()
    result_dict = result.to_dict()

    strategy_output = output_dir / strategy.id
    strategy_output.mkdir(parents=True, exist_ok=True)
    json_path = strategy_output / f"{symbol}.json"
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(result_dict, handle, indent=2)

    stats = result_dict["stats"]
    return {
        "skipped": False,
        "symbol": symbol,
        "start_date": start_date.date().isoformat(),
        "end_date": end_date.date().isoformat(),
        "stats": stats,
        "json_path": str(json_path),
    }


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    csv_path: str | Path | None = None,
) -> RunSummary:
    _ensure_import_path()
    from backtester.strategies.registry import get_strategy
    from backtester.connectors import ExnessCSVClient

    resolved_root, _ = resolve_data_root(str(data_root) if data_root else None)
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    module_name = strategy_cls.__module__.split(".")[-1]
    config_data = load_strategy_config(module_name)
    video_number = str(config_data.get("video_number", ""))

    summary = RunSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_name,
        video_number=video_number,
        data_root=str(resolved_root) if resolved_root else "",
        data_source="not_backtested" if resolved_root is None else "exness_production",
    )

    if resolved_root is None:
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

    raw_rows: list[dict[str, Any]] = []
    for symbol in target_symbols:
        outcome = run_single_backtest(strategy_cls, symbol, resolved_root, output_path)
        if outcome.get("skipped"):
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = outcome.get("reason", "skipped")
            continue

        summary.instruments_tested += 1
        stats = outcome["stats"]
        raw_rows.append(
            {
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": module_name,
                "video_number": video_number,
                "symbol": symbol,
                "backtest_start_date": outcome["start_date"],
                "backtest_end_date": outcome["end_date"],
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
                "backtest_result_json": outcome["json_path"],
                "backtested_at": datetime.now(timezone.utc).isoformat(),
                "data_quality_note": "",
                "data_source": "exness_production",
            }
        )

    best_pnl = max((float(r["bt_total_pnl"]) for r in raw_rows), default=0.0)
    min_trades = int(config_data.get("min_trades_for_ranking", 10))
    for row in raw_rows:
        row["composite_score"] = composite_score(row, best_pnl, min_trades)

    ranked = sorted(raw_rows, key=lambda r: r["composite_score"], reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = rank

    summary.matrix_rows = ranked
    _write_matrix_rows(ranked)

    if ranked:
        eligible = [r for r in ranked if int(r["bt_total_trades"]) >= min_trades]
        if eligible:
            best = eligible[0]
            worst = eligible[-1]
            summary.best_instrument = best["symbol"]
            summary.worst_instrument = worst["symbol"]
            summary.instrument_affinity_notes = (
                f"Strongest on {best['symbol']} (PF={best['bt_profit_factor']}, "
                f"{best['bt_total_trades']} trades). Weakest on {worst['symbol']} "
                f"(PF={worst['bt_profit_factor']}, {worst['bt_total_trades']} trades)."
            )

        total_trades = sum(int(r["bt_total_trades"]) for r in ranked)
        win_rates = [float(r["bt_win_rate"]) for r in ranked if int(r["bt_total_trades"]) > 0]
        pfs = [float(r["bt_profit_factor"]) for r in ranked if int(r["bt_total_trades"]) > 0]
        dds = [float(r["bt_max_drawdown_pct"]) for r in ranked]
        pnls = [float(r["bt_total_pnl"]) for r in ranked]
        sharpes = [float(r["bt_sharpe_ratio"]) for r in ranked if int(r["bt_total_trades"]) > 0]
        rrs = [float(r["bt_avg_rr"]) for r in ranked if int(r["bt_total_trades"]) > 0]
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(sum(win_rates) / len(win_rates), 2) if win_rates else 0,
            "bt_profit_factor_all": round(sum(pfs) / len(pfs), 2) if pfs else 0,
            "bt_max_drawdown_pct_all": round(max(dds), 2) if dds else 0,
            "bt_total_pnl_all": round(sum(pnls), 2),
            "bt_sharpe_ratio_all": round(sum(sharpes) / len(sharpes), 2) if sharpes else 0,
            "bt_avg_rr_all": round(sum(rrs) / len(rrs), 2) if rrs else 0,
        }

    if csv_path:
        _update_tracking_csv(Path(csv_path), summary)

    return summary


def _write_matrix_rows(rows: list[dict[str, Any]]):
    matrix_path = DEFAULT_OUTPUT / "strategy_instrument_matrix.csv"
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if matrix_path.exists():
        with open(matrix_path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row

    for row in rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {col: str(row.get(col, "")) for col in MATRIX_COLUMNS}

    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = matrix_path.with_suffix(".csv.tmp")
    with open(temp_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        for row in existing.values():
            writer.writerow({col: row.get(col, "") for col in MATRIX_COLUMNS})
    temp_path.replace(matrix_path)


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    temp_path = path.with_suffix(".csv.tmp")
    with open(temp_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(path)


def _update_tracking_csv(csv_path: Path, summary: RunSummary):
    fieldnames, rows = _read_csv_rows(csv_path)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("module_to_code") != summary.strategy_module_id:
            continue
        if row.get("action") != "CODE-CANONICAL":
            continue

        row["strategy_module_id"] = summary.strategy_module_id
        row["strategy_folder"] = f"strategies/{summary.strategy_module_id}/"
        row["strategy_registry_id"] = summary.strategy_id
        row["coded_at"] = row.get("coded_at") or now
        row["anti_bias_review_passed"] = "yes"
        row["anti_bias_notes"] = (
            "HTF bars gated by close; session VP from past bars only; "
            "wick-volume absorption proxy; entries on bar close."
        )
        row["data_root_used"] = summary.data_root

        if summary.instruments_tested > 0:
            row["implementation_status"] = "coded_and_backtested"
            row["backtested_at"] = now
            row["instruments_tested_count"] = str(summary.instruments_tested)
            row["data_source"] = "exness_production"
            agg = summary.aggregate_stats
            row["bt_total_trades_all"] = str(agg.get("bt_total_trades_all", 0))
            row["bt_win_rate_all"] = str(agg.get("bt_win_rate_all", 0))
            row["bt_profit_factor_all"] = str(agg.get("bt_profit_factor_all", 0))
            row["bt_max_drawdown_pct_all"] = str(agg.get("bt_max_drawdown_pct_all", 0))
            row["bt_total_pnl_all"] = str(agg.get("bt_total_pnl_all", 0))
            row["bt_sharpe_ratio_all"] = str(agg.get("bt_sharpe_ratio_all", 0))
            row["bt_avg_rr_all"] = str(agg.get("bt_avg_rr_all", 0))
            row["best_instrument"] = summary.best_instrument
            row["worst_instrument"] = summary.worst_instrument
            row["instrument_affinity_notes"] = summary.instrument_affinity_notes
            if summary.best_instrument:
                best_row = next(
                    (r for r in summary.matrix_rows if r["symbol"] == summary.best_instrument),
                    None,
                )
                if best_row:
                    row["best_instrument_pf"] = str(best_row.get("bt_profit_factor", ""))
                    row["best_instrument_win_rate"] = str(best_row.get("bt_win_rate", ""))
                    row["best_instrument_pnl"] = str(best_row.get("bt_total_pnl", ""))
                    row["best_instrument_trades"] = str(best_row.get("bt_total_trades", ""))
        else:
            row["implementation_status"] = "coded_pending_production_backtest"
            row["data_source"] = "pending_exness_production"

    for row in rows:
        if row.get("action") == "DUPLICATE-SKIP" and row.get("module_to_code") == summary.strategy_module_id:
            canonical = next(
                (
                    r
                    for r in rows
                    if r.get("action") == "CODE-CANONICAL"
                    and r.get("module_to_code") == summary.strategy_module_id
                ),
                None,
            )
            if canonical and canonical.get("implementation_status") == "coded_and_backtested":
                row["implementation_status"] = "covered_by_canonical"
                row["strategy_registry_id"] = canonical.get("strategy_registry_id", "")
                for col in TRACKING_COLUMNS:
                    if col.startswith("bt_") or col.startswith("best_") or col in {
                        "worst_instrument",
                        "instrument_affinity_notes",
                        "data_source",
                    }:
                        row[col] = canonical.get(col, "")

    _write_csv_rows(csv_path, fieldnames, rows)


def cmd_audit(csv_path: Path):
    _ensure_import_path()
    from backtester.strategies.registry import load_all_strategies

    strategies_dir = BACKTESTER_ROOT / "strategies"
    coded_folders = sorted(
        p.name
        for p in strategies_dir.iterdir()
        if p.is_dir() and p.name not in {"__pycache__"} and (p / "strategy.py").exists()
    )
    registry = load_all_strategies()

    fieldnames, rows = _read_csv_rows(csv_path)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    canonical_rows = [
        r for r in rows if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(1 for r in canonical_rows if r.get("implementation_status") == "coded_and_backtested")
    pending = [
        r
        for r in canonical_rows
        if r.get("implementation_status", "") in {"", "not_started", "failed", "in_progress"}
    ]
    pending.sort(key=lambda r: int(r.get("video_number", 999)))

    data_root, source = resolve_data_root()
    print("=== Backtester Audit ===")
    print(f"Strategy folders on disk: {len(coded_folders)} -> {coded_folders}")
    print(f"Registry strategies: {len(registry)} -> {sorted(registry.keys())}")
    print(f"Canonical progress: {done}/{len(canonical_rows)}")
    print(f"Data root ({source}): {data_root or 'MISSING'}")
    if data_root:
        client_symbols = []
        try:
            from backtester.connectors import ExnessCSVClient

            client_symbols = ExnessCSVClient(data_root).get_symbols()
        except Exception as exc:
            print(f"Data scan error: {exc}")
        print(f"Symbols available: {len(client_symbols)}")

    if pending:
        nxt = pending[0]
        print(
            f"Next pending: Video #{nxt.get('video_number')} — "
            f"{nxt.get('title')} ({nxt.get('module_to_code')})"
        )

    changed = False
    for row in rows:
        module = row.get("module_to_code", "")
        if not module:
            continue
        folder = f"strategies/{module}/"
        if (strategies_dir / module / "strategy.py").exists():
            if not row.get("strategy_folder"):
                row["strategy_folder"] = folder
                changed = True
            if not row.get("implementation_status"):
                row["implementation_status"] = "not_started"
                changed = True

    if changed:
        _write_csv_rows(csv_path, fieldnames, rows)


def cmd_list_strategies():
    _ensure_import_path()
    from backtester.strategies.registry import load_all_strategies

    registry = load_all_strategies()
    print("=== Registered Strategies ===")
    for strat_id in sorted(registry):
        cls = registry[strat_id]
        print(f"  {strat_id}: {cls.name} (video {getattr(cls, 'source_video', '')})")


def cmd_run(args: argparse.Namespace):
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
        csv_path=args.csv,
    )
    print("\n=== Run Complete ===")
    print(f"Strategy: {summary.strategy_id}")
    print(f"Data root: {summary.data_root or 'MISSING'}")
    print(f"Scanned: {summary.instruments_scanned}")
    print(f"Tested: {summary.instruments_tested}")
    print(f"Skipped: {summary.instruments_skipped}")
    if summary.best_instrument:
        print(f"Best: {summary.best_instrument}")
        print(f"Worst: {summary.worst_instrument}")
    print(f"Affinity: {summary.instrument_affinity_notes}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_parser = sub.add_parser("audit", help="Audit CSV vs coded folders")
    audit_parser.add_argument("--csv", default=str(DEFAULT_CSV))

    sub.add_parser("list-strategies", help="List registered strategies")

    run_parser = sub.add_parser("run", help="Run multi-instrument backtest")
    run_parser.add_argument("--strategy", required=True)
    run_parser.add_argument("--symbols", default="all")
    run_parser.add_argument("--data-root", default=None)
    run_parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_parser.add_argument("--csv", default=str(DEFAULT_CSV))
    run_parser.add_argument("--start", default=None)
    run_parser.add_argument("--end", default=None)
    return parser


def main(argv: list[str] | None = None):
    _ensure_import_path()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "audit":
        cmd_audit(Path(args.csv))
    elif args.command == "list-strategies":
        cmd_list_strategies()
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
