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
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure backtester package is importable
_DOCS_ROOT = Path(__file__).resolve().parent.parent
if str(_DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(_DOCS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient, resolve_data_root
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_strategy, list_strategy_ids, load_all_strategies

BACKTESTER_ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = _DOCS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
MATRIX_CSV = DEFAULT_OUTPUT / "strategy_instrument_matrix.csv"

TRACKING_COLUMNS = [
    "implementation_status", "strategy_module_id", "strategy_folder", "strategy_registry_id",
    "coded_at", "backtested_at", "instruments_tested_count", "anti_bias_review_passed",
    "anti_bias_notes", "backtest_error", "data_source", "data_root_used",
    "bt_total_trades_all", "bt_win_rate_all", "bt_profit_factor_all", "bt_max_drawdown_pct_all",
    "bt_total_pnl_all", "bt_sharpe_ratio_all", "bt_avg_rr_all",
    "best_instrument", "best_instrument_pf", "best_instrument_win_rate", "best_instrument_pnl",
    "best_instrument_trades", "worst_instrument", "instrument_affinity_notes",
]

MATRIX_COLUMNS = [
    "strategy_registry_id", "strategy_module_id", "video_number", "symbol",
    "backtest_start_date", "backtest_end_date", "bt_total_trades", "bt_winning_trades",
    "bt_losing_trades", "bt_win_rate", "bt_profit_factor", "bt_max_drawdown_pct",
    "bt_total_pnl", "bt_sharpe_ratio", "bt_avg_rr", "bt_avg_trade_duration_mins",
    "composite_score", "rank_within_strategy", "backtest_result_json", "backtested_at",
    "data_quality_note", "data_source",
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
class MultiInstrumentSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: int
    best_instrument: str = ""
    worst_instrument: str = ""
    matrix_rows: list[dict] = field(default_factory=list)
    aggregate_stats: dict = field(default_factory=dict)
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_yaml_defaults(strategy_cls) -> dict:
    module_path = Path(sys.modules[strategy_cls.__module__].__file__).parent
    cfg_path = module_path / "config.yaml"
    if not cfg_path.exists():
        return {}
    import yaml
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def composite_score(row: dict, max_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0))
    if trades < min_trades:
        return 0.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0) / 5.0 * 0.35
    wr = float(row.get("bt_win_rate", 0) or 0) / 100.0 * 0.20
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    sharpe_norm = min(max(sharpe, -2), 3) / 3.0 * 0.20
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    pnl_norm = (pnl / max_pnl) * 0.15 if max_pnl > 0 else 0.0
    trade_norm = min(trades, 50) / 50.0 * 0.10
    return round(pf + wr + sharpe_norm + pnl_norm + trade_norm, 4)


def run_single_backtest(
    strategy_id: str,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[Any | None, str]:
    strategy_cls = get_strategy(strategy_id)
    if not strategy_cls:
        return None, f"Strategy not found: {strategy_id}"

    cfg_yaml = _load_yaml_defaults(strategy_cls)
    bt_defaults = cfg_yaml.get("backtest_defaults", {})
    required_tfs = [tf_from_string(t) for t in cfg_yaml.get("required_timeframes", [])]
    if not required_tfs:
        required_tfs = list(strategy_cls.timeframes)

    for tf in required_tfs:
        if not client.has_timeframe(symbol, tf):
            return None, f"Missing timeframe {tf.name} for {symbol}"

    full_start, full_end = client.get_full_date_range(symbol, required_tfs)
    if not full_start or not full_end:
        return None, f"No data for {symbol}"

    start_date = start or full_start
    end_date = end or full_end

    config = BacktestConfig(
        strategy_id=strategy_id,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_balance=float(bt_defaults.get("initial_balance", 10000.0)),
        risk_per_trade=float(bt_defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(bt_defaults.get("spread_pips", 1.0)),
        slippage_pips=float(bt_defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(bt_defaults.get("commission_per_lot", 7.0)),
    )

    strategy = strategy_cls()
    engine = BacktestEngine(config, strategy, client)
    result = engine.run()

    strat_dir = output_dir / strategy_id
    strat_dir.mkdir(parents=True, exist_ok=True)
    json_path = strat_dir / f"{symbol}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)

    return result, ""


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    data_source: str = "exness_production",
) -> MultiInstrumentSummary:
    client = ExnessCSVClient(data_root)
    output_dir = Path(output_dir or DEFAULT_OUTPUT)
    output_dir.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if not strategy_cls:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module_name = strategy_cls.__module__.split(".")[-1]
    cfg_yaml = _load_yaml_defaults(strategy_cls)
    video_number = int(cfg_yaml.get("video_number", 0))
    min_trades = int(cfg_yaml.get("min_trades_for_ranking", 10))

    if symbols == "all":
        symbol_list = client.get_symbols()
    elif isinstance(symbols, str):
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        symbol_list = list(symbols)

    summary = MultiInstrumentSummary(
        strategy_id=strategy_id,
        strategy_module_id=module_name,
        video_number=video_number,
        instruments_scanned=len(symbol_list),
        data_source=data_source,
        data_root_used=str(data_root),
    )

    instrument_results: list[InstrumentResult] = []

    for symbol in symbol_list:
        result, note = run_single_backtest(strategy_id, symbol, client, output_dir, start, end)
        if result is None:
            summary.instruments_skipped += 1
            instrument_results.append(InstrumentResult(symbol=symbol, result=None, skipped=True, data_quality_note=note))
            continue

        summary.instruments_tested += 1
        stats = result.to_dict()["stats"]
        row = {
            "strategy_registry_id": strategy_id,
            "strategy_module_id": module_name,
            "video_number": video_number,
            "symbol": symbol,
            "backtest_start_date": result.config.start_date.date().isoformat(),
            "backtest_end_date": result.config.end_date.date().isoformat(),
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
            "backtested_at": _utcnow_iso(),
            "data_quality_note": note,
            "data_source": data_source,
            "backtest_result_json": str(output_dir / strategy_id / f"{symbol}.json"),
        }
        instrument_results.append(InstrumentResult(symbol=symbol, result=result, data_quality_note=note))

        max_pnl = max(
            (float(r.result.to_dict()["stats"]["total_pnl"]) for r in instrument_results if r.result),
            default=0.0,
        )
        row["composite_score"] = composite_score(row, max_pnl, min_trades)
        summary.matrix_rows.append(row)

    # Recompute scores with global max pnl and rank
    tested_rows = [r for r in summary.matrix_rows if r.get("bt_total_trades", 0) >= 0]
    max_pnl = max((float(r.get("bt_total_pnl", 0)) for r in tested_rows), default=0.0)
    for row in summary.matrix_rows:
        row["composite_score"] = composite_score(row, max_pnl, min_trades)

    ranked = sorted(summary.matrix_rows, key=lambda r: r["composite_score"], reverse=True)
    for i, row in enumerate(ranked, 1):
        row["rank_within_strategy"] = i

    _update_matrix_csv(summary.matrix_rows)

    # Aggregate stats
    if tested_rows:
        total_trades = sum(int(r["bt_total_trades"]) for r in tested_rows)
        total_wins = sum(int(r["bt_winning_trades"]) for r in tested_rows)
        total_pnl = sum(float(r["bt_total_pnl"]) for r in tested_rows)
        gross_profit = sum(float(r["bt_total_pnl"]) for r in tested_rows if float(r["bt_total_pnl"]) > 0)
        gross_loss = abs(sum(float(r["bt_total_pnl"]) for r in tested_rows if float(r["bt_total_pnl"]) <= 0))
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0,
            "bt_profit_factor_all": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
            "bt_max_drawdown_pct_all": max(float(r["bt_max_drawdown_pct"]) for r in tested_rows),
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(
                sum(float(r["bt_sharpe_ratio"]) for r in tested_rows) / len(tested_rows), 2
            ),
            "bt_avg_rr_all": round(
                sum(float(r["bt_avg_rr"]) for r in tested_rows) / len(tested_rows), 2
            ),
        }

        eligible = [r for r in ranked if int(r["bt_total_trades"]) >= min_trades]
        if eligible:
            best = eligible[0]
            worst = eligible[-1]
            summary.best_instrument = best["symbol"]
            summary.worst_instrument = worst["symbol"]

    return summary


def _update_matrix_csv(new_rows: list[dict]):
    MATRIX_CSV.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[str, str], dict] = {}
    if MATRIX_CSV.exists():
        with open(MATRIX_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row

    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {col: str(row.get(col, "")) for col in MATRIX_COLUMNS}

    _atomic_write_csv(MATRIX_CSV, MATRIX_COLUMNS, list(existing.values()))


def _atomic_write_csv(path: Path, fieldnames: list[str], rows: list[dict]):
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


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        return 1

    load_all_strategies()
    registered = list_strategy_ids()

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    canonical = [r for r in rows if r.get("action") == "CODE-CANONICAL"]
    coded = [r for r in canonical if r.get("implementation_status") in ("coded_and_backtested", "coded_pending_production_backtest", "coded")]
    backtester_dir = BACKTESTER_ROOT
    has_main = (backtester_dir / "main_backtester.py").exists()
    has_core = (backtester_dir / "core" / "engine.py").exists()
    data_root = resolve_data_root(args.data_root)
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_root else 0

    print("=== Backtester Audit ===")
    print(f"Infra: main_backtester={has_main}, core={has_core}")
    print(f"Registered strategies: {registered}")
    print(f"Canonical modules: {len(canonical)} total, {len(coded)} with code status")
    print(f"Data root: {data_root or 'NOT AVAILABLE'} ({symbol_count} symbols)")

    for r in canonical:
        mod = r.get("module_to_code", "")
        status = r.get("implementation_status", "not_started") or "not_started"
        folder = backtester_dir / "strategies" / mod
        exists = folder.is_dir()
        print(f"  Video #{r.get('video_number')} {mod}: status={status}, folder={exists}")

    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    load_all_strategies()
    for sid in list_strategy_ids():
        cls = get_strategy(sid)
        print(f"{sid}: {cls.name} (video {cls.source_video})")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    data_root = resolve_data_root(args.data_root)
    if not data_root:
        print("No real Exness history found. Cannot run production backtest.")
        print("Set --data-root or LOCAL_HISTORY_PATH to Exness structured history.")
        return 1

    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=data_root,
        symbols=args.symbols,
        output_dir=args.output,
        data_source="exness_production",
    )

    print(f"\nBacktest complete: {summary.instruments_tested} tested, {summary.instruments_skipped} skipped")
    if summary.best_instrument:
        print(f"Best: {summary.best_instrument}")
    if summary.worst_instrument:
        print(f"Worst: {summary.worst_instrument}")
    return 0


def update_strategy_csv(
    csv_path: Path,
    video_number: str,
    updates: dict,
    propagate_duplicates: bool = False,
):
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    canonical_module = None
    for row in rows:
        if row.get("video_number") == str(video_number):
            row.update({k: str(v) if v is not None else "" for k, v in updates.items()})
            canonical_module = row.get("module_to_code")

    if propagate_duplicates and canonical_module and updates.get("data_source") == "exness_production":
        for row in rows:
            if row.get("action") == "DUPLICATE-SKIP" and row.get("module_to_code") == canonical_module:
                row["implementation_status"] = "covered_by_canonical"
                for k, v in updates.items():
                    if k.startswith("bt_") or k.startswith("best_") or k in ("worst_instrument", "instrument_affinity_notes"):
                        row[k] = str(v) if v is not None else ""

    _atomic_write_csv(csv_path, fieldnames, rows)


def main():
    parser = argparse.ArgumentParser(description="Faiz SMC Strategy Backtester")
    sub = parser.add_subparsers(dest="command")

    audit_p = sub.add_parser("audit", help="Audit CSV vs coded strategies vs data")
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
        sys.exit(cmd_audit(args))
    if args.command == "list-strategies":
        sys.exit(cmd_list_strategies(args))
    if args.command == "run":
        sys.exit(cmd_run(args))
    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
