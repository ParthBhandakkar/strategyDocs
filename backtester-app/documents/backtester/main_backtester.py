#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, run multi-instrument backtests.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
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
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies

DEFAULT_CSV = _DOCS_ROOT / "video_docs" / "strategy_videos_90.csv"
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
    composite_score: float = 0.0
    rank: int = 0
    data_quality_note: str = ""
    skipped: bool = False


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    module_id: str
    video_number: str
    best_instrument: str = ""
    worst_instrument: str = ""
    matrix_rows: list[dict] = field(default_factory=list)
    aggregate_stats: dict = field(default_factory=dict)
    instrument_results: list[InstrumentResult] = field(default_factory=list)
    data_source: str = "not_backtested"
    data_root_used: str = ""
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_csv_columns(csv_path: Path) -> list[str]:
    rows, fieldnames = _read_csv(csv_path)
    changed = False
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
            changed = True
    if changed:
        _write_csv(csv_path, fieldnames, rows)
    return fieldnames


def _read_csv(csv_path: Path) -> tuple[list[dict], list[str]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return rows, fieldnames


def _write_csv(csv_path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=csv_path.parent, suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        with tmp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        tmp_path.replace(csv_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _load_strategy_config(strategy_cls) -> dict:
    module = strategy_cls.__module__.split(".")[-1]
    config_path = Path(__file__).resolve().parent / "strategies" / module / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    with config_path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _required_timeframes(strategy_cls) -> list[TF]:
    config = _load_strategy_config(strategy_cls)
    tfs = config.get("required_timeframes")
    if tfs:
        return [tf_from_string(str(tf)) for tf in tfs]
    return list(strategy_cls.timeframes)


def _backtest_defaults(strategy_cls) -> dict:
    config = _load_strategy_config(strategy_cls)
    defaults = config.get("backtest_defaults", {})
    return {
        "initial_balance": float(defaults.get("initial_balance", 10000.0)),
        "risk_per_trade": float(defaults.get("risk_per_trade", 0.01)),
        "spread_pips": float(defaults.get("spread_pips", 1.0)),
        "slippage_pips": float(defaults.get("slippage_pips", 0.5)),
        "commission_per_lot": float(defaults.get("commission_per_lot", 7.0)),
    }


def _composite_score(row: dict, best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades") or 0)
    if trades < min_trades:
        return -1.0
    pf = min(float(row.get("bt_profit_factor") or 0), 5.0)
    win_rate = float(row.get("bt_win_rate") or 0)
    sharpe = float(row.get("bt_sharpe_ratio") or 0)
    pnl = float(row.get("bt_total_pnl") or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    return (
        (pf / 5.0 * 0.35)
        + (win_rate / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10)
    )


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    load_all_strategies()
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    resolved_root = resolve_data_root(str(data_root) if data_root else None)
    module_id = strategy_cls.__module__.split(".")[-1]
    config = _load_strategy_config(strategy_cls)
    video_number = str(config.get("video_number", strategy_cls.source_video or ""))
    defaults = _backtest_defaults(strategy_cls)
    required_tfs = _required_timeframes(strategy_cls)
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        module_id=module_id,
        video_number=video_number,
        data_root_used=str(resolved_root) if resolved_root else "",
    )

    if resolved_root is None:
        summary.data_source = "pending_exness_production"
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

    summary.data_source = "exness_production"
    instrument_results: list[InstrumentResult] = []
    now_iso = _utc_now_iso()

    for symbol in target_symbols:
        if not client.has_timeframes(symbol, required_tfs):
            instrument_results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=None,
                    skipped=True,
                    data_quality_note=f"Missing required timeframes: {[tf.name for tf in required_tfs]}",
                )
            )
            summary.instruments_skipped += 1
            continue

        sym_start, sym_end = client.get_full_date_range(symbol, required_tfs)
        if sym_start is None or sym_end is None:
            instrument_results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=None,
                    skipped=True,
                    data_quality_note="No date range available",
                )
            )
            summary.instruments_skipped += 1
            continue

        bt_start = start or sym_start
        bt_end = end or sym_end

        bt_config = BacktestConfig(
            strategy_id=strategy_cls.id,
            symbol=symbol,
            start_date=bt_start,
            end_date=bt_end,
            initial_balance=defaults["initial_balance"],
            risk_per_trade=defaults["risk_per_trade"],
            spread_pips=defaults["spread_pips"],
            slippage_pips=defaults["slippage_pips"],
            commission_per_lot=defaults["commission_per_lot"],
        )

        strategy = strategy_cls()
        engine = BacktestEngine(bt_config, strategy, client)
        result = engine.run()
        summary.instruments_tested += 1

        result_json_path = output_path / strategy_cls.id / f"{symbol}.json"
        result_json_path.parent.mkdir(parents=True, exist_ok=True)
        with result_json_path.open("w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle, indent=2)

        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_id,
            "video_number": video_number,
            "symbol": symbol,
            "backtest_start_date": bt_start.date().isoformat(),
            "backtest_end_date": bt_end.date().isoformat(),
            "bt_total_trades": result.total_trades,
            "bt_winning_trades": result.winning_trades,
            "bt_losing_trades": result.losing_trades,
            "bt_win_rate": result.win_rate,
            "bt_profit_factor": result.profit_factor if math.isfinite(result.profit_factor) else 999.0,
            "bt_max_drawdown_pct": result.max_drawdown_pct,
            "bt_total_pnl": result.total_pnl,
            "bt_sharpe_ratio": result.sharpe_ratio,
            "bt_avg_rr": result.avg_rr,
            "bt_avg_trade_duration_mins": result.avg_trade_duration,
            "composite_score": 0.0,
            "rank_within_strategy": 0,
            "backtest_result_json": str(result_json_path),
            "backtested_at": now_iso,
            "data_quality_note": "",
            "data_source": "exness_production",
        }
        instrument_results.append(InstrumentResult(symbol=symbol, result=result, composite_score=0.0))
        summary.matrix_rows.append(row)

    if summary.matrix_rows:
        best_pnl = max(float(r["bt_total_pnl"]) for r in summary.matrix_rows)
        min_trades = int(config.get("min_trades_for_ranking", 10))
        for row in summary.matrix_rows:
            row["composite_score"] = round(_composite_score(row, best_pnl, min_trades), 4)

        ranked = sorted(
            [r for r in summary.matrix_rows if float(r["composite_score"]) >= 0],
            key=lambda r: float(r["composite_score"]),
            reverse=True,
        )
        for idx, row in enumerate(ranked, start=1):
            row["rank_within_strategy"] = idx

        if ranked:
            best = ranked[0]
            worst = ranked[-1]
            summary.best_instrument = best["symbol"]
            summary.worst_instrument = worst["symbol"]

        summary.aggregate_stats = _aggregate_stats(summary.matrix_rows)
        _update_matrix_csv(summary.matrix_rows)

    summary.instrument_results = instrument_results
    return summary


def _aggregate_stats(rows: list[dict]) -> dict:
    if not rows:
        return {}
    total_trades = sum(int(r["bt_total_trades"]) for r in rows)
    if total_trades == 0:
        return {
            "bt_total_trades_all": 0,
            "bt_win_rate_all": 0.0,
            "bt_profit_factor_all": 0.0,
            "bt_max_drawdown_pct_all": max(float(r["bt_max_drawdown_pct"]) for r in rows),
            "bt_total_pnl_all": sum(float(r["bt_total_pnl"]) for r in rows),
            "bt_sharpe_ratio_all": 0.0,
            "bt_avg_rr_all": 0.0,
        }
    weighted_wr = sum(float(r["bt_win_rate"]) * int(r["bt_total_trades"]) for r in rows) / total_trades
    gross_profit = sum(max(float(r["bt_total_pnl"]), 0) for r in rows)
    gross_loss = abs(sum(min(float(r["bt_total_pnl"]), 0) for r in rows))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    return {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": round(weighted_wr, 2),
        "bt_profit_factor_all": round(pf, 2) if math.isfinite(pf) else 999.0,
        "bt_max_drawdown_pct_all": round(max(float(r["bt_max_drawdown_pct"]) for r in rows), 2),
        "bt_total_pnl_all": round(sum(float(r["bt_total_pnl"]) for r in rows), 2),
        "bt_sharpe_ratio_all": round(
            sum(float(r["bt_sharpe_ratio"]) for r in rows) / len(rows),
            2,
        ),
        "bt_avg_rr_all": round(
            sum(float(r["bt_avg_rr"]) * int(r["bt_total_trades"]) for r in rows) / total_trades,
            2,
        ),
    }


def _update_matrix_csv(new_rows: list[dict]) -> None:
    MATRIX_CSV.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[str, str], dict] = {}
    if MATRIX_CSV.exists():
        with MATRIX_CSV.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row
    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = row
    merged = list(existing.values())
    _write_csv(MATRIX_CSV, MATRIX_COLUMNS, merged)


def cmd_audit(csv_path: Path) -> int:
    _ensure_csv_columns(csv_path)
    rows, _ = _read_csv(csv_path)
    load_all_strategies()
    strategies = get_all_strategies()
    registered = {
        s.id: s.__module__.rsplit(".", 1)[0].split(".")[-1] for s in strategies
    }

    backtester_root = Path(__file__).resolve().parent
    strategy_folders = [
        p.name
        for p in (backtester_root / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__"}
    ]

    data_root = resolve_data_root()
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_root else 0

    canonical = [r for r in rows if r.get("action") == "CODE-CANONICAL"]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")
    pending = sum(
        1
        for r in canonical
        if r.get("implementation_status") in ("", "not_started", "in_progress", "failed")
    )

    print("=== Backtester Audit ===")
    print(f"Backtester root: {backtester_root}")
    print(f"main_backtester.py: exists")
    print(f"Registered strategies: {len(registered)}")
    for sid, mod in sorted(registered.items()):
        print(f"  - {sid} ({mod})")
    print(f"Strategy folders on disk: {strategy_folders}")
    print(f"Data root: {data_root or 'NOT AVAILABLE'}")
    print(f"Symbols in data root: {symbol_count}")
    print(f"Canonical modules: {len(canonical)} total, {done} coded_and_backtested, {pending} pending")
    return 0


def cmd_list_strategies() -> int:
    load_all_strategies()
    for strategy_cls in get_all_strategies():
        module = strategy_cls.__module__.rsplit(".", 1)[0].split(".")[-1]
        print(f"{strategy_cls.id}\t{module}\t{strategy_cls.name}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    print(f"\nStrategy: {summary.strategy_id}")
    print(f"Data source: {summary.data_source}")
    print(f"Instruments scanned: {summary.instruments_scanned}")
    print(f"Instruments tested: {summary.instruments_tested}")
    print(f"Instruments skipped: {summary.instruments_skipped}")
    if summary.best_instrument:
        print(f"Best instrument: {summary.best_instrument}")
        print(f"Worst instrument: {summary.worst_instrument}")
    return 0


def update_tracking_csv(
    csv_path: Path,
    video_number: str,
    updates: dict[str, str],
) -> None:
    fieldnames = _ensure_csv_columns(csv_path)
    rows, _ = _read_csv(csv_path)
    for row in rows:
        if str(row.get("video_number")) == str(video_number):
            row.update(updates)
    _write_csv(csv_path, fieldnames, rows)


def propagate_duplicate_rows(csv_path: Path, canonical_video: str) -> None:
    fieldnames = _ensure_csv_columns(csv_path)
    rows, _ = _read_csv(csv_path)
    canonical = next((r for r in rows if str(r.get("video_number")) == str(canonical_video)), None)
    if not canonical or canonical.get("data_source") != "exness_production":
        return
    if canonical.get("implementation_status") != "coded_and_backtested":
        return
    module = canonical.get("module_to_code", "")
    copy_fields = [
        "implementation_status",
        "strategy_registry_id",
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
        "data_source",
    ]
    for row in rows:
        if row.get("action") == "DUPLICATE-SKIP" and row.get("module_to_code") == module:
            row["implementation_status"] = "covered_by_canonical"
            for field in copy_fields:
                if field in canonical:
                    row[field] = canonical[field]
    _write_csv(csv_path, fieldnames, rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit CSV vs coded strategies vs data")
    audit_p.add_argument("--csv", default=str(DEFAULT_CSV))

    sub.add_parser("list-strategies", help="List registered strategies")

    run_p = sub.add_parser("run", help="Run multi-instrument backtest")
    run_p.add_argument("--strategy", required=True)
    run_p.add_argument("--symbols", default="all")
    run_p.add_argument("--data-root", default=None)
    run_p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_p.add_argument("--start", default=None)
    run_p.add_argument("--end", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "audit":
        return cmd_audit(Path(args.csv))
    if args.command == "list-strategies":
        return cmd_list_strategies()
    if args.command == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
