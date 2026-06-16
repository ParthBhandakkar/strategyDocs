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

# Ensure backtester package is importable
_DOCS_ROOT = Path(__file__).resolve().parent.parent
if str(_DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(_DOCS_ROOT))

import yaml

from backtester.connectors.exness_csv import ExnessCSVClient, resolve_data_root
from backtester.core import BacktestConfig, BacktestResult
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BACKTESTER_ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = _DOCS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
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
    result: BacktestResult | None
    error: str = ""
    data_quality_note: str = ""
    composite_score: float = 0.0
    rank: int = 0


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    module_id: str
    video_number: str
    best_instrument: str = ""
    worst_instrument: str = ""
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def _load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _parse_symbols_arg(symbols: str, client: ExnessCSVClient) -> list[str]:
    if symbols.strip().lower() == "all":
        return client.get_symbols()
    return [s.strip().upper() for s in symbols.split(",") if s.strip()]


def composite_score(
    pf: float,
    win_rate: float,
    sharpe: float,
    pnl: float,
    trades: int,
    best_pnl: float,
    min_trades: int = 10,
) -> float:
    if trades < min_trades:
        return 0.0
    pf_norm = min(pf, 5) / 5 * 0.35
    wr_norm = win_rate / 100 * 0.20
    sharpe_norm = min(max(sharpe, -2), 3) / 3 * 0.20
    pnl_norm = (pnl / best_pnl * 0.15) if best_pnl > 0 else 0.0
    trade_norm = min(trades, 50) / 50 * 0.10
    return round(pf_norm + wr_norm + sharpe_norm + pnl_norm + trade_norm, 4)


def run_single_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    start: datetime,
    end: datetime,
    backtest_defaults: dict[str, Any],
) -> BacktestResult:
    strategy = strategy_cls()
    config = BacktestConfig(
        strategy_id=strategy.id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=float(backtest_defaults.get("initial_balance", 10000.0)),
        risk_per_trade=float(backtest_defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(backtest_defaults.get("spread_pips", 1.0)),
        slippage_pips=float(backtest_defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(backtest_defaults.get("commission_per_lot", 7.0)),
    )
    engine = BacktestEngine(config, strategy, client)
    return engine.run()


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    resolved_root = resolve_data_root(data_root)
    summary = MultiInstrumentSummary(strategy_id=strategy_id, module_id="", video_number="")

    if resolved_root is None:
        logger.warning("No Exness history path available — backtest skipped")
        summary.data_source = "pending_exness_production"
        return summary

    summary.data_root_used = str(resolved_root)
    summary.data_source = "exness_production"

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module_name = strategy_cls.__module__.split(".")[-1]
    summary.module_id = module_name
    config_yaml = _load_strategy_config(module_name)
    summary.video_number = str(config_yaml.get("video_number", ""))
    backtest_defaults = config_yaml.get("backtest_defaults", {})
    required_tfs = [
        tf_from_string(tf) for tf in config_yaml.get("required_timeframes", [])
    ] or list(strategy_cls.timeframes)
    min_trades = int(config_yaml.get("min_trades_for_ranking", 10))

    client = ExnessCSVClient(resolved_root)
    symbol_list = _parse_symbols_arg(symbols, client)
    summary.instruments_scanned = len(symbol_list)

    results: list[InstrumentResult] = []

    for symbol in symbol_list:
        available = client.get_available_timeframes(symbol)
        missing = [tf for tf in required_tfs if tf not in available]
        if missing:
            summary.instruments_skipped += 1
            results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=None,
                    error="missing_timeframes",
                    data_quality_note=f"Missing: {[tf.name for tf in missing]}",
                )
            )
            continue

        sym_start, sym_end = client.get_full_date_range(symbol, required_tfs)
        if not sym_start or not sym_end:
            summary.instruments_skipped += 1
            results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=None,
                    error="no_date_range",
                    data_quality_note="Could not determine date range",
                )
            )
            continue

        bt_start = start or sym_start
        bt_end = end or sym_end

        try:
            bt_result = run_single_backtest(
                strategy_cls, symbol, client, bt_start, bt_end, backtest_defaults
            )
            summary.instruments_tested += 1
            results.append(InstrumentResult(symbol=symbol, result=bt_result))
        except Exception as exc:
            summary.instruments_skipped += 1
            results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=None,
                    error=str(exc),
                    data_quality_note=f"Backtest error: {exc}",
                )
            )

    best_pnl = max(
        (r.result.total_pnl for r in results if r.result),
        default=0.0,
    )
    if best_pnl <= 0:
        best_pnl = 1.0

    for ir in results:
        if ir.result and ir.result.total_trades > 0:
            ir.composite_score = composite_score(
                ir.result.profit_factor,
                ir.result.win_rate,
                ir.result.sharpe_ratio,
                ir.result.total_pnl,
                ir.result.total_trades,
                best_pnl,
                min_trades,
            )

    ranked = sorted(
        [r for r in results if r.result],
        key=lambda r: r.composite_score,
        reverse=True,
    )
    for rank, ir in enumerate(ranked, start=1):
        ir.rank = rank

    now_iso = datetime.now(timezone.utc).isoformat()
    strategy_result_dir = output_path / strategy_id
    strategy_result_dir.mkdir(parents=True, exist_ok=True)

    for ir in results:
        if not ir.result:
            continue
        json_path = strategy_result_dir / f"{ir.symbol}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(ir.result.to_dict(), f, indent=2)

    matrix_rows: list[dict[str, Any]] = []
    for ir in results:
        if not ir.result:
            row = {
                "strategy_registry_id": strategy_id,
                "strategy_module_id": module_name,
                "video_number": summary.video_number,
                "symbol": ir.symbol,
                "data_quality_note": ir.data_quality_note or ir.error,
                "data_source": summary.data_source,
                "backtested_at": now_iso,
            }
            matrix_rows.append(row)
            continue

        r = ir.result
        row = {
            "strategy_registry_id": strategy_id,
            "strategy_module_id": module_name,
            "video_number": summary.video_number,
            "symbol": ir.symbol,
            "backtest_start_date": r.config.start_date.date().isoformat(),
            "backtest_end_date": r.config.end_date.date().isoformat(),
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
            "composite_score": ir.composite_score,
            "rank_within_strategy": ir.rank,
            "backtest_result_json": str(strategy_result_dir / f"{ir.symbol}.json"),
            "backtested_at": now_iso,
            "data_quality_note": ir.data_quality_note,
            "data_source": summary.data_source,
        }
        matrix_rows.append(row)

    summary.matrix_rows = matrix_rows
    _update_matrix_csv(matrix_rows, strategy_id)

    qualifying = [r for r in ranked if r.result and r.result.total_trades >= min_trades]
    if qualifying:
        best = qualifying[0]
        worst = qualifying[-1]
        summary.best_instrument = best.symbol
        summary.worst_instrument = worst.symbol

    all_trades = sum(r.result.total_trades for r in results if r.result)
    if all_trades > 0:
        total_pnl = sum(r.result.total_pnl for r in results if r.result)
        win_rates = [r.result.win_rate for r in results if r.result and r.result.total_trades > 0]
        pfs = [r.result.profit_factor for r in results if r.result and r.result.total_trades > 0]
        dds = [r.result.max_drawdown_pct for r in results if r.result]
        sharpes = [r.result.sharpe_ratio for r in results if r.result and r.result.total_trades > 0]
        rrs = [r.result.avg_rr for r in results if r.result and r.result.total_trades > 0]
        summary.aggregate_stats = {
            "bt_total_trades_all": all_trades,
            "bt_win_rate_all": round(sum(win_rates) / len(win_rates), 2) if win_rates else 0,
            "bt_profit_factor_all": round(sum(pfs) / len(pfs), 2) if pfs else 0,
            "bt_max_drawdown_pct_all": round(max(dds), 2) if dds else 0,
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(sum(sharpes) / len(sharpes), 2) if sharpes else 0,
            "bt_avg_rr_all": round(sum(rrs) / len(rrs), 2) if rrs else 0,
        }

    return summary


def _update_matrix_csv(rows: list[dict[str, Any]], strategy_id: str):
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if MATRIX_CSV.exists():
        with open(MATRIX_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for row in rows:
        key = (row.get("strategy_registry_id", strategy_id), row.get("symbol", ""))
        if key[1]:
            merged = existing.get(key, {})
            merged.update({k: str(v) for k, v in row.items() if v is not None})
            existing[key] = merged

    all_rows = list(existing.values())
    fieldnames = list(MATRIX_COLUMNS)
    for row in all_rows:
        for k in row:
            if k not in fieldnames:
                fieldnames.append(k)

    _atomic_write_csv(MATRIX_CSV, fieldnames, all_rows)


def _atomic_write_csv(path: Path, fieldnames: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".csv.tmp")
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


def cmd_audit(csv_path: Path):
    rows, fieldnames = _read_tracking_csv(csv_path)
    load_all_strategies()
    coded_modules = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__"}
        and (p / "strategy.py").exists()
    }

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    print(f"\n=== Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Canonical modules: {len(canonical)}")
    print(f"Coded folders on disk: {len(coded_modules)}")
    for mod in sorted(coded_modules):
        print(f"  - strategies/{mod}/")

    data_root = resolve_data_root(None)
    if data_root:
        client = ExnessCSVClient(data_root)
        syms = client.get_symbols()
        print(f"Data root: {data_root} ({len(syms)} symbols)")
    else:
        print("Data root: NOT AVAILABLE (production backtest pending)")

    status_counts: dict[str, int] = {}
    for r in canonical:
        st = r.get("implementation_status") or "not_started"
        status_counts[st] = status_counts.get(st, 0) + 1
    print("Canonical status:")
    for st, cnt in sorted(status_counts.items()):
        print(f"  {st}: {cnt}")


def _read_tracking_csv(csv_path: Path) -> tuple[list[dict], list[str]]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return rows, fieldnames


def cmd_list_strategies():
    strategies = get_all_strategies()
    print(f"\nRegistered strategies ({len(strategies)}):")
    for cls in sorted(strategies, key=lambda c: c.id):
        print(f"  {cls.id} — {cls.name} [{', '.join(tf.name for tf in cls.timeframes)}]")


def cmd_run(args):
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    print(f"\nMulti-instrument backtest complete: {summary.strategy_id}")
    print(f"  Scanned: {summary.instruments_scanned}")
    print(f"  Tested:  {summary.instruments_tested}")
    print(f"  Skipped: {summary.instruments_skipped}")
    if summary.best_instrument:
        print(f"  Best: {summary.best_instrument}")
    return summary


def update_tracking_csv(
    csv_path: Path,
    video_number: str,
    updates: dict[str, Any],
    propagate_duplicates: bool = False,
):
    rows, fieldnames = _read_tracking_csv(csv_path)
    canonical_module = updates.get("strategy_module_id", "")

    for row in rows:
        vn = str(row.get("video_number", ""))
        if vn == str(video_number):
            row.update({k: str(v) if v is not None else "" for k, v in updates.items()})
        elif (
            propagate_duplicates
            and row.get("action") == "DUPLICATE-SKIP"
            and row.get("duplicate_of_video") == str(video_number)
            and updates.get("data_source") == "exness_production"
            and updates.get("implementation_status") == "coded_and_backtested"
        ):
            row["implementation_status"] = "covered_by_canonical"
            for k in TRACKING_COLUMNS:
                if k.startswith("bt_") or k.startswith("best_") or k.startswith("worst_"):
                    if k in updates:
                        row[k] = str(updates[k])

    _atomic_write_csv(csv_path, fieldnames, rows)


def main():
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
    run_p.add_argument("--start", default=None)
    run_p.add_argument("--end", default=None)

    args = parser.parse_args()
    if args.command == "audit":
        cmd_audit(Path(args.csv))
    elif args.command == "list-strategies":
        cmd_list_strategies()
    elif args.command == "run":
        cmd_run(args)


if __name__ == "__main__":
    main()
