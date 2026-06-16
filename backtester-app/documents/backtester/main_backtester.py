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
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
DEFAULT_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
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


def _ensure_pythonpath() -> None:
    documents = str(DOCUMENTS_ROOT)
    if documents not in sys.path:
        sys.path.insert(0, documents)


def resolve_data_root(cli_arg: str | None) -> Path:
    if cli_arg:
        return Path(cli_arg)
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path and Path(env_path).is_dir():
        symbols = [d for d in Path(env_path).iterdir() if d.is_dir()]
        if symbols:
            return Path(env_path)
    return Path(DEFAULT_DATA_ROOT)


def data_root_is_real(path: Path) -> bool:
    if not path.is_dir():
        return False
    for sym_dir in path.iterdir():
        if not sym_dir.is_dir():
            continue
        for tf_dir in sym_dir.iterdir():
            if tf_dir.is_dir() and list(tf_dir.glob("*.csv")):
                return True
    return False


def load_strategy_config(module: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def composite_score(
    pf: float,
    win_rate: float,
    sharpe: float,
    pnl: float,
    trades: int,
    best_pnl: float,
) -> float:
    sharpe_norm = min(max(sharpe, -2), 3) / 3
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    return (
        (min(pf, 5) / 5 * 0.35)
        + (win_rate / 100 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50 * 0.10)
    )


@dataclass
class RunSummary:
    strategy_id: str
    module: str
    video_number: int
    data_root: str
    data_source: str
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    best_instrument: str = ""
    worst_instrument: str = ""
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    affinity_notes: str = ""


def run_single_backtest(
    strategy_cls,
    symbol: str,
    data_root: Path,
    output_dir: Path,
) -> tuple[dict[str, Any] | None, str]:
    _ensure_pythonpath()
    from backtester.connectors import ExnessCSVClient
    from backtester.core import BacktestConfig
    from backtester.core.engine import BacktestEngine
    from backtester.core.timeframes import TF, tf_from_string

    config_data = load_strategy_config(strategy_cls.__module__.split(".")[-2])
    defaults = config_data.get("backtest_defaults", {})
    required_tf_strs = config_data.get("required_timeframes", ["M1"])
    required_tfs = [tf_from_string(s) for s in required_tf_strs]

    client = ExnessCSVClient(str(data_root))
    start, end = client.get_full_date_range(symbol, required_tfs)
    if not start or not end:
        return None, f"Missing required timeframes {required_tf_strs}"

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

    result_dict = result.to_dict()
    json_dir = output_dir / strategy.id
    json_dir.mkdir(parents=True, exist_ok=True)
    json_path = json_dir / f"{symbol}.json"
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(result_dict, handle, indent=2)

    stats = result_dict["stats"]
    row = {
        "symbol": symbol,
        "backtest_start_date": start.date().isoformat(),
        "backtest_end_date": end.date().isoformat(),
        "bt_total_trades": stats["total_trades"],
        "bt_winning_trades": stats["winning_trades"],
        "bt_losing_trades": stats["losing_trades"],
        "bt_win_rate": stats["win_rate"],
        "bt_profit_factor": stats["profit_factor"] if stats["profit_factor"] != float("inf") else 99.99,
        "bt_max_drawdown_pct": stats["max_drawdown_pct"],
        "bt_total_pnl": stats["total_pnl"],
        "bt_sharpe_ratio": stats["sharpe_ratio"],
        "bt_avg_rr": stats["avg_rr"],
        "bt_avg_trade_duration_mins": stats["avg_trade_duration_mins"],
        "backtest_result_json": str(json_path.relative_to(BACKTESTER_ROOT)),
        "data_quality_note": "",
    }
    return row, ""


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> RunSummary:
    _ensure_pythonpath()
    from backtester.strategies.registry import get_strategy

    root = Path(data_root) if data_root else resolve_data_root(None)
    out = Path(output_dir) if output_dir else DEFAULT_OUTPUT
    out.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    config_data = load_strategy_config(strategy_cls.__module__.split(".")[-2])
    video_number = int(config_data.get("video_number", 0))
    module = config_data.get("module", strategy_id.split("_", 1)[-1])
    min_trades = int(config_data.get("min_trades_for_ranking", 10))

    is_real = data_root_is_real(root)
    data_source = "exness_production" if is_real else "not_backtested"

    from backtester.connectors import ExnessCSVClient
    client = ExnessCSVClient(str(root))
    all_symbols = client.get_symbols() if is_real else []

    if isinstance(symbols, str) and symbols.lower() == "all":
        target_symbols = all_symbols
    elif isinstance(symbols, str):
        target_symbols = [s.strip().upper() for s in symbols.split(",")]
    else:
        target_symbols = [s.upper() for s in symbols]

    summary = RunSummary(
        strategy_id=strategy_cls.id,
        module=module,
        video_number=video_number,
        data_root=str(root),
        data_source=data_source,
        instruments_scanned=len(target_symbols),
    )

    if not is_real:
        summary.instruments_skipped = len(target_symbols)
        summary.skip_reasons["all"] = "Production data path unavailable"
        return summary

    rows: list[dict[str, Any]] = []
    for symbol in target_symbols:
        try:
            row, err = run_single_backtest(strategy_cls, symbol, root, out)
            if row is None:
                summary.instruments_skipped += 1
                summary.skip_reasons[symbol] = err
                continue
            row["strategy_registry_id"] = strategy_cls.id
            row["strategy_module_id"] = module
            row["video_number"] = video_number
            row["backtested_at"] = datetime.now(timezone.utc).isoformat()
            row["data_source"] = data_source
            rows.append(row)
            summary.instruments_tested += 1
        except Exception as exc:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = str(exc)

    if not rows:
        return summary

    best_pnl = max(r["bt_total_pnl"] for r in rows)
    for row in rows:
        row["composite_score"] = round(
            composite_score(
                row["bt_profit_factor"],
                row["bt_win_rate"],
                row["bt_sharpe_ratio"],
                row["bt_total_pnl"],
                row["bt_total_trades"],
                best_pnl,
            ),
            4,
        )

    ranked = sorted(rows, key=lambda r: r["composite_score"], reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = rank

    eligible = [r for r in ranked if r["bt_total_trades"] >= min_trades]
    if eligible:
        best = eligible[0]
        worst = eligible[-1]
        summary.best_instrument = best["symbol"]
        summary.worst_instrument = worst["symbol"]

    total_trades = sum(r["bt_total_trades"] for r in rows)
    total_wins = sum(r["bt_winning_trades"] for r in rows)
    total_pnl = sum(r["bt_total_pnl"] for r in rows)
    pf_vals = [r["bt_profit_factor"] for r in rows if r["bt_total_trades"] > 0]
    dd_vals = [r["bt_max_drawdown_pct"] for r in rows]
    sharpe_vals = [r["bt_sharpe_ratio"] for r in rows if r["bt_total_trades"] > 0]
    rr_vals = [r["bt_avg_rr"] for r in rows if r["bt_total_trades"] > 0]

    summary.aggregate_stats = {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0,
        "bt_profit_factor_all": round(sum(pf_vals) / len(pf_vals), 2) if pf_vals else 0,
        "bt_max_drawdown_pct_all": round(max(dd_vals), 2) if dd_vals else 0,
        "bt_total_pnl_all": round(total_pnl, 2),
        "bt_sharpe_ratio_all": round(sum(sharpe_vals) / len(sharpe_vals), 2) if sharpe_vals else 0,
        "bt_avg_rr_all": round(sum(rr_vals) / len(rr_vals), 2) if rr_vals else 0,
    }

    strong = [r for r in eligible if r["bt_profit_factor"] > 1.5 and r["bt_total_trades"] >= 10]
    weak = [r for r in eligible if r["bt_profit_factor"] < 1.0]
    if strong:
        strong_syms = ", ".join(r["symbol"] for r in strong[:3])
        summary.affinity_notes = f"Strong on {strong_syms} (PF>1.5, 10+ trades)."
    if weak:
        weak_syms = ", ".join(r["symbol"] for r in weak[:3])
        summary.affinity_notes += f" Weak on {weak_syms} (PF<1.0)."

    summary.matrix_rows = ranked
    _update_matrix_csv(ranked)
    return summary


def _update_matrix_csv(rows: list[dict[str, Any]]) -> None:
    MATRIX_CSV.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if MATRIX_CSV.exists():
        with open(MATRIX_CSV, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row

    for row in rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {col: str(row.get(col, "")) for col in MATRIX_COLUMNS}

    with open(MATRIX_CSV, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda r: (r["strategy_registry_id"], r["symbol"])):
            writer.writerow(row)


def _atomic_csv_write(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        return 1

    _ensure_pythonpath()
    from backtester.strategies.registry import list_strategy_ids, load_all_strategies

    load_all_strategies()
    coded_ids = set(list_strategy_ids())

    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    canonical = [r for r in rows if r.get("action") == "CODE-CANONICAL"]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")
    pending = sum(
        1 for r in canonical
        if r.get("implementation_status") in ("", "not_started", "in_progress", "failed")
    )

    print(f"Canonical modules: {len(canonical)}")
    print(f"Completed (coded_and_backtested): {done}")
    print(f"Pending: {pending}")
    print(f"Registered strategies: {sorted(coded_ids)}")

    data_root = resolve_data_root(args.data_root)
    real = data_root_is_real(data_root)
    print(f"Data root: {data_root} ({'REAL' if real else 'MISSING'})")

    folders = [
        d.name for d in (BACKTESTER_ROOT / "strategies").iterdir()
        if d.is_dir() and d.name not in ("__pycache__",)
    ]
    print(f"Strategy folders on disk: {sorted(folders)}")
    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    _ensure_pythonpath()
    from backtester.strategies.registry import get_all_strategies, load_all_strategies

    load_all_strategies()
    for cls in get_all_strategies():
        print(f"{cls.id}\t{cls.name}\t{cls.source_video}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        summary = run_multi_instrument_backtest(
            strategy_id=args.strategy,
            data_root=args.data_root,
            symbols=args.symbols,
            output_dir=args.output,
        )
    except Exception as exc:
        print(f"Backtest failed: {exc}")
        return 1

    print(f"Strategy: {summary.strategy_id}")
    print(f"Data source: {summary.data_source}")
    print(f"Instruments tested: {summary.instruments_tested}")
    print(f"Instruments skipped: {summary.instruments_skipped}")
    if summary.best_instrument:
        print(f"Best: {summary.best_instrument}")
    if summary.aggregate_stats:
        print(f"Aggregate: {summary.aggregate_stats}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Strategy backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit_p.add_argument("--csv", default=str(DEFAULT_CSV))
    audit_p.add_argument("--data-root", default=None)

    sub.add_parser("list-strategies", help="List registered strategies")

    run_p = sub.add_parser("run", help="Run multi-instrument backtest")
    run_p.add_argument("--strategy", required=True)
    run_p.add_argument("--symbols", default="all")
    run_p.add_argument("--data-root", default=None)
    run_p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_p.add_argument("--start", default=None)
    run_p.add_argument("--end", default=None)

    args = parser.parse_args()
    if args.command == "audit":
        return cmd_audit(args)
    if args.command == "list-strategies":
        return cmd_list_strategies(args)
    if args.command == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
