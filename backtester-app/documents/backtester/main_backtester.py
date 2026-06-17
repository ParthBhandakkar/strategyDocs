#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, and multi-instrument runs.
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
from typing import Any, Optional

# Ensure backtester package resolves when run as a script
_DOCS_ROOT = Path(__file__).resolve().parent.parent
if str(_DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(_DOCS_ROOT))

import yaml

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_strategy, list_strategy_ids, load_all_strategies

DEFAULT_WINDOWS_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
DEFAULT_CSV = _DOCS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "results"

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
class RunSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: Optional[str] = None
    worst_instrument: Optional[str] = None
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_root: str | None = None) -> tuple[str, bool]:
    if cli_root:
        path = Path(cli_root)
        if path.is_dir() and ExnessCSVClient(path).get_symbols():
            return str(path), True
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path and Path(env_path).is_dir() and ExnessCSVClient(env_path).get_symbols():
        return env_path, True
    win_path = Path(DEFAULT_WINDOWS_DATA_ROOT)
    if win_path.is_dir() and ExnessCSVClient(win_path).get_symbols():
        return str(win_path), True
    return cli_root or env_path or DEFAULT_WINDOWS_DATA_ROOT, False


def _load_strategy_config(module: str) -> dict[str, Any]:
    cfg_path = Path(__file__).resolve().parent / "strategies" / module / "config.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _parse_symbols_arg(symbols: str, client: ExnessCSVClient) -> list[str]:
    if symbols.strip().lower() == "all":
        return client.get_symbols()
    return [s.strip().upper() for s in symbols.split(",") if s.strip()]


def composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades") or 0)
    if trades < min_trades:
        return 0.0
    pf = min(float(row.get("bt_profit_factor") or 0), 5.0)
    wr = float(row.get("bt_win_rate") or 0)
    sharpe = float(row.get("bt_sharpe_ratio") or 0)
    pnl = float(row.get("bt_total_pnl") or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    return (
        (pf / 5.0 * 0.35)
        + (wr / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10)
    )


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    defaults: dict[str, Any],
    required_tfs: list[TF],
) -> dict[str, Any]:
    start, end, missing = client.get_full_date_range(symbol, required_tfs)
    if missing or start is None or end is None:
        return {
            "symbol": symbol,
            "skipped": True,
            "data_quality_note": f"missing_timeframes:{','.join(missing)}",
        }

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
    out_path = output_dir / strategy_cls.id / f"{symbol}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, indent=2)

    stats = result_dict["stats"]
    return {
        "symbol": symbol,
        "skipped": False,
        "backtest_start_date": start.date().isoformat(),
        "backtest_end_date": end.date().isoformat(),
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
        "backtest_result_json": str(out_path),
        "data_quality_note": "",
    }


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str = "all",
    output_dir: str | Path | None = None,
    data_available: bool | None = None,
) -> RunSummary:
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    module = strategy_id.split("_", 1)[-1] if "_" in strategy_id else strategy_id
    cfg = _load_strategy_config(module)
    defaults = cfg.get("backtest_defaults", {})
    required_tf_names = cfg.get("required_timeframes") or [tf.name for tf in strategy_cls.timeframes]
    required_tfs = [tf_from_string(name) for name in required_tf_names]
    min_trades = int(cfg.get("min_trades_for_ranking", 10))
    video_number = str(cfg.get("video_number", ""))

    root, found = resolve_data_root(data_root)
    if data_available is None:
        data_available = found

    out_dir = Path(output_dir or DEFAULT_OUTPUT)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = RunSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module,
        video_number=video_number,
        data_source="exness_production" if data_available else "pending_exness_production",
        data_root_used=root,
    )

    if not data_available:
        return summary

    client = ExnessCSVClient(root)
    symbol_list = _parse_symbols_arg(symbols, client)
    summary.instruments_scanned = len(symbol_list)

    raw_rows: list[dict[str, Any]] = []
    for symbol in symbol_list:
        row = run_single_symbol_backtest(strategy_cls, symbol, client, out_dir, defaults, required_tfs)
        if row.get("skipped"):
            summary.instruments_skipped += 1
            continue
        summary.instruments_tested += 1
        row.update(
            {
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": module,
                "video_number": video_number,
                "backtested_at": datetime.now(timezone.utc).isoformat(),
                "data_source": "exness_production",
            }
        )
        raw_rows.append(row)

    best_pnl = max((float(r["bt_total_pnl"]) for r in raw_rows), default=0.0)
    for row in raw_rows:
        row["composite_score"] = round(composite_score(row, best_pnl, min_trades), 4)

    ranked = sorted(raw_rows, key=lambda r: r["composite_score"], reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = rank

    summary.matrix_rows = ranked

    if ranked:
        eligible = [r for r in ranked if int(r["bt_total_trades"]) >= min_trades]
        if eligible:
            summary.best_instrument = eligible[0]["symbol"]
            summary.worst_instrument = eligible[-1]["symbol"]

        total_trades = sum(int(r["bt_total_trades"]) for r in ranked)
        total_wins = sum(int(r["bt_winning_trades"]) for r in ranked)
        total_pnl = sum(float(r["bt_total_pnl"]) for r in ranked)
        pf_vals = [float(r["bt_profit_factor"]) for r in ranked if r["bt_total_trades"]]
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0,
            "bt_profit_factor_all": round(sum(pf_vals) / len(pf_vals), 2) if pf_vals else 0,
            "bt_max_drawdown_pct_all": round(max(float(r["bt_max_drawdown_pct"]) for r in ranked), 2),
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(
                sum(float(r["bt_sharpe_ratio"]) for r in ranked) / len(ranked), 2
            ),
            "bt_avg_rr_all": round(sum(float(r["bt_avg_rr"]) for r in ranked) / len(ranked), 2),
        }

    _write_matrix_csv(out_dir / "strategy_instrument_matrix.csv", summary.matrix_rows, strategy_cls.id)
    return summary


def _write_matrix_csv(path: Path, new_rows: list[dict[str, Any]], strategy_id: str):
    existing: dict[tuple[str, str], dict[str, str]] = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for row in new_rows:
        key = (strategy_id, row["symbol"])
        existing[key] = {col: str(row.get(col, "")) for col in MATRIX_COLUMNS if col in row or col in MATRIX_COLUMNS}
        for col in MATRIX_COLUMNS:
            existing[key].setdefault(col, str(row.get(col, "")))

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda r: (r.get("strategy_registry_id", ""), r.get("symbol", ""))):
            writer.writerow({col: row.get(col, "") for col in MATRIX_COLUMNS})


def _ensure_csv_columns(csv_path: Path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    return fieldnames, rows


def _atomic_write_csv(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", delete=False, dir=csv_path.parent) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in fieldnames})
        tmp_path = tmp.name
    os.replace(tmp_path, csv_path)


def audit(csv_path: Path) -> dict[str, Any]:
    fieldnames, rows = _ensure_csv_columns(csv_path)
    load_all_strategies()
    coded_modules = {
        p.name
        for p in (Path(__file__).resolve().parent / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__", "tests"}
    }

    canonical = [r for r in rows if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"]
    pending = [
        r for r in canonical
        if r.get("implementation_status", "not_started") in ("", "not_started", "failed", "in_progress")
    ]

    data_root, data_ok = resolve_data_root()
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_ok else 0

    return {
        "csv_path": str(csv_path),
        "canonical_total": len(canonical),
        "canonical_pending": len(pending),
        "strategy_folders_on_disk": sorted(coded_modules),
        "registered_strategies": list_strategy_ids(),
        "data_root": data_root,
        "data_available": data_ok,
        "symbol_count": symbol_count,
        "next_pending": pending[0] if pending else None,
    }


def cmd_audit(args: argparse.Namespace) -> int:
    report = audit(Path(args.csv))
    print(json.dumps(report, indent=2, default=str))
    return 0


def cmd_list_strategies(_: argparse.Namespace) -> int:
    load_all_strategies()
    for sid in list_strategy_ids():
        cls = get_strategy(sid)
        print(f"{sid}\t{cls.name if cls else '?'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    data_root, data_ok = resolve_data_root(args.data_root)
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=data_root,
        symbols=args.symbols,
        output_dir=args.output,
        data_available=data_ok,
    )
    print(json.dumps({
        "strategy_id": summary.strategy_id,
        "data_source": summary.data_source,
        "instruments_scanned": summary.instruments_scanned,
        "instruments_tested": summary.instruments_tested,
        "instruments_skipped": summary.instruments_skipped,
        "best_instrument": summary.best_instrument,
        "worst_instrument": summary.worst_instrument,
        "aggregate_stats": summary.aggregate_stats,
    }, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="Audit CSV vs coded strategies vs data")
    p_audit.add_argument("--csv", default=str(DEFAULT_CSV))

    sub.add_parser("list-strategies", help="List registered strategy IDs")

    p_run = sub.add_parser("run", help="Run multi-instrument backtest")
    p_run.add_argument("--strategy", required=True)
    p_run.add_argument("--symbols", default="all")
    p_run.add_argument("--data-root", default=None)
    p_run.add_argument("--output", default=str(DEFAULT_OUTPUT))
    p_run.add_argument("--start", default=None)
    p_run.add_argument("--end", default=None)

    args = parser.parse_args(argv)
    if args.command == "audit":
        return cmd_audit(args)
    if args.command == "list-strategies":
        return cmd_list_strategies(args)
    if args.command == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
