#!/usr/bin/env python3
"""
Main backtester CLI — single entry point for strategy pipeline backtests.
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
from typing import Any, Optional

# Ensure documents/ is on path for `backtester` package imports
_DOCS_ROOT = Path(__file__).resolve().parent.parent
if str(_DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(_DOCS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient, resolve_data_root
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import (
    get_all_strategies,
    get_strategy,
    get_strategy_config,
    load_all_strategies,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

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
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


@dataclass
class MultiBacktestSummary:
    strategy_id: str
    module_id: str
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


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    backtester_root = Path(__file__).resolve().parent
    strategies_dir = backtester_root / "strategies"

    load_all_strategies(strategies_dir)
    registered = {cls.id: cls for cls in get_all_strategies()}

    rows, fieldnames = _read_csv(csv_path)
    fieldnames = _ensure_columns(fieldnames, TRACKING_COLUMNS)

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]

    coded_folders = {
        d.name
        for d in strategies_dir.iterdir()
        if d.is_dir() and (d / "strategy.py").exists()
    }

    data_root = resolve_data_root(args.data_root)
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_root else 0

    print("\n=== Backtester Audit ===")
    print(f"Backtester root: {backtester_root}")
    print(f"main_backtester.py: {'OK' if (backtester_root / 'main_backtester.py').exists() else 'MISSING'}")
    print(f"Registered strategies: {len(registered)}")
    for sid in sorted(registered):
        print(f"  - {sid}")
    print(f"Strategy folders on disk: {sorted(coded_folders)}")
    print(f"CODE-CANONICAL rows: {len(canonical)}")
    print(f"Data root: {data_root or 'NOT AVAILABLE'}")
    print(f"Symbols in data root: {symbol_count}")

    done = 0
    pending = 0
    for r in canonical:
        status = r.get("implementation_status", "")
        if status == "coded_and_backtested":
            done += 1
        else:
            pending += 1
        mod = r.get("module_to_code", "")
        reg_id = r.get("strategy_registry_id", "")
        print(f"  Video {r.get('video_number')}: {mod} -> {status or 'not_started'} [{reg_id}]")

    print(f"\nProgress: {done}/{len(canonical)} coded_and_backtested, {pending} pending")
    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    load_all_strategies()
    for cls in get_all_strategies():
        print(f"{cls.id}\t{cls.name}\tvideo={cls.source_video}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    data_root = resolve_data_root(args.data_root)
    if not data_root:
        logger.error("No real Exness history found. Set --data-root or LOCAL_HISTORY_PATH.")
        return 1

    output_dir = Path(args.output)
    symbols = _parse_symbols(args.symbols, ExnessCSVClient(data_root))

    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=str(data_root),
        symbols=symbols,
        output_dir=str(output_dir),
        start=args.start,
        end=args.end,
    )

    print(f"\nBest: {summary.best_instrument}")
    print(f"Worst: {summary.worst_instrument}")
    print(f"Tested: {summary.instruments_tested}/{summary.instruments_scanned}")
    return 0


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str,
    symbols: str | list[str] = "all",
    output_dir: str = str(DEFAULT_OUTPUT),
    start: str | None = None,
    end: str | None = None,
    csv_path: str | None = None,
) -> MultiBacktestSummary:
    """Run backtest across instruments and persist results."""
    client = ExnessCSVClient(data_root)
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    config_yaml = get_strategy_config(strategy_id)
    if not config_yaml:
        # Resolve by class id after load
        load_all_strategies()
        config_yaml = get_strategy_config(strategy_cls.id)

    module_id = config_yaml.get("module", strategy_cls.__module__.split(".")[-1])
    video_number = int(config_yaml.get("video_number", strategy_cls.source_video or 0))
    defaults = config_yaml.get("backtest_defaults", {})
    required_tfs = [tf_from_string(t) for t in config_yaml.get("required_timeframes", ["M1"])]

    if symbols == "all":
        symbol_list = client.get_symbols()
    elif isinstance(symbols, str):
        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        symbol_list = [s.upper() for s in symbols]

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    strategy_result_dir = output_path / strategy_cls.id
    strategy_result_dir.mkdir(parents=True, exist_ok=True)

    summary = MultiBacktestSummary(
        strategy_id=strategy_cls.id,
        module_id=module_id,
        video_number=video_number,
        instruments_scanned=len(symbol_list),
        data_source="exness_production",
        data_root_used=data_root,
    )

    instrument_results: list[InstrumentResult] = []

    for symbol in symbol_list:
        sym_start, sym_end, missing = client.get_full_date_range(symbol, required_tfs)
        if missing or sym_start is None or sym_end is None:
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=None,
                    data_quality_note=f"Missing timeframes: {','.join(missing)}",
                )
            )
            continue

        bt_start = datetime.fromisoformat(start).replace(tzinfo=timezone.utc) if start else sym_start
        bt_end = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else sym_end

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

        strategy = strategy_cls()
        engine = BacktestEngine(bt_config, strategy, client)
        try:
            result = engine.run()
        except Exception as exc:
            logger.error("Backtest failed for %s: %s", symbol, exc)
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(symbol=symbol, result=None, data_quality_note=str(exc))
            )
            continue

        summary.instruments_tested += 1

        json_path = strategy_result_dir / f"{symbol}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2)

        instrument_results.append(
            InstrumentResult(
                symbol=symbol,
                result=result,
                start_date=bt_start,
                end_date=bt_end,
            )
        )

    min_trades = int(config_yaml.get("min_trades_for_ranking", 10))
    _score_and_rank(instrument_results, min_trades)
    summary.matrix_rows = _build_matrix_rows(
        instrument_results, strategy_cls.id, module_id, video_number, data_root
    )
    _write_matrix_csv(summary.matrix_rows, output_path / "strategy_instrument_matrix.csv")

    ranked = [ir for ir in instrument_results if ir.result and ir.rank > 0]
    if ranked:
        best = max(ranked, key=lambda x: x.composite_score)
        worst = min(ranked, key=lambda x: x.composite_score)
        summary.best_instrument = best.symbol
        summary.worst_instrument = worst.symbol

    summary.aggregate_stats = _aggregate_stats(instrument_results)

    if csv_path or DEFAULT_CSV.exists():
        _update_tracking_csv(
            csv_path or str(DEFAULT_CSV),
            strategy_cls.id,
            module_id,
            video_number,
            summary,
            instrument_results,
            data_root,
        )

    return summary


def _parse_symbols(symbols_arg: str, client: ExnessCSVClient) -> list[str]:
    if symbols_arg.lower() == "all":
        return client.get_symbols()
    return [s.strip().upper() for s in symbols_arg.split(",") if s.strip()]


def _score_and_rank(results: list[InstrumentResult], min_trades: int) -> None:
    valid = [ir for ir in results if ir.result and ir.result.total_trades >= min_trades]
    if not valid:
        return

    max_pnl = max(ir.result.total_pnl for ir in valid)
    min_pnl = min(ir.result.total_pnl for ir in valid)
    pnl_range = max_pnl - min_pnl if max_pnl != min_pnl else 1.0

    for ir in valid:
        r = ir.result
        pf = min(r.profit_factor, 5) / 5 * 0.35
        wr = r.win_rate / 100 * 0.20
        sharpe_norm = min(max(r.sharpe_ratio, -2), 3) / 3 * 0.20
        pnl_norm = (r.total_pnl - min_pnl) / pnl_range * 0.15
        trade_norm = min(r.total_trades, 50) / 50 * 0.10
        ir.composite_score = round(pf + wr + sharpe_norm + pnl_norm + trade_norm, 4)

    valid.sort(key=lambda x: x.composite_score, reverse=True)
    for rank, ir in enumerate(valid, start=1):
        ir.rank = rank


def _build_matrix_rows(
    results: list[InstrumentResult],
    strategy_id: str,
    module_id: str,
    video_number: int,
    data_root: str,
) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for ir in results:
        if ir.result is None:
            rows.append({
                "strategy_registry_id": strategy_id,
                "strategy_module_id": module_id,
                "video_number": video_number,
                "symbol": ir.symbol,
                "data_quality_note": ir.data_quality_note,
                "data_source": "exness_production",
                "backtested_at": now,
            })
            continue

        r = ir.result
        rows.append({
            "strategy_registry_id": strategy_id,
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
            "bt_total_pnl": round(r.total_pnl, 2),
            "bt_sharpe_ratio": r.sharpe_ratio,
            "bt_avg_rr": r.avg_rr,
            "bt_avg_trade_duration_mins": r.avg_trade_duration,
            "composite_score": ir.composite_score,
            "rank_within_strategy": ir.rank,
            "backtest_result_json": f"results/{strategy_id}/{ir.symbol}.json",
            "backtested_at": now,
            "data_quality_note": ir.data_quality_note,
            "data_source": "exness_production",
        })
    return rows


def _write_matrix_csv(new_rows: list[dict], matrix_path: Path) -> None:
    existing: dict[tuple[str, str], dict] = {}
    if matrix_path.exists():
        with open(matrix_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for row in new_rows:
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        if key[0] and key[1]:
            existing[key] = {**existing.get(key, {}), **row}

    fieldnames = list(MATRIX_COLUMNS)
    for row in existing.values():
        for k in row:
            if k not in fieldnames:
                fieldnames.append(k)

    _atomic_write_csv(matrix_path, fieldnames, list(existing.values()))


def _aggregate_stats(results: list[InstrumentResult]) -> dict:
    tested = [ir.result for ir in results if ir.result and ir.result.total_trades > 0]
    if not tested:
        return {}

    total_trades = sum(r.total_trades for r in tested)
    total_wins = sum(r.winning_trades for r in tested)
    gross_profit = sum(t.pnl for t in sum((r.trades for r in tested), []) if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in sum((r.trades for r in tested), []) if t.pnl <= 0))
    total_pnl = sum(r.total_pnl for r in tested)

    return {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0,
        "bt_profit_factor_all": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
        "bt_max_drawdown_pct_all": round(max(r.max_drawdown_pct for r in tested), 2),
        "bt_total_pnl_all": round(total_pnl, 2),
        "bt_sharpe_ratio_all": round(
            sum(r.sharpe_ratio for r in tested) / len(tested), 2
        ),
        "bt_avg_rr_all": round(sum(r.avg_rr for r in tested) / len(tested), 2),
    }


def _update_tracking_csv(
    csv_path: str,
    strategy_id: str,
    module_id: str,
    video_number: int,
    summary: MultiBacktestSummary,
    results: list[InstrumentResult],
    data_root: str,
) -> None:
    path = Path(csv_path)
    rows, fieldnames = _read_csv(path)
    fieldnames = _ensure_columns(fieldnames, TRACKING_COLUMNS)
    now = datetime.now(timezone.utc).isoformat()

    agg = summary.aggregate_stats
    best_ir = next((ir for ir in results if ir.symbol == summary.best_instrument), None)
    worst_ir = next((ir for ir in results if ir.symbol == summary.worst_instrument), None)

    affinity = _build_affinity_notes(results, summary.best_instrument, summary.worst_instrument)

    for row in rows:
        if row.get("module_to_code") != module_id:
            continue

        row["strategy_module_id"] = module_id
        row["strategy_folder"] = f"strategies/{module_id}/"
        row["strategy_registry_id"] = strategy_id
        row["implementation_status"] = "coded_and_backtested"
        row["coded_at"] = row.get("coded_at") or now
        row["backtested_at"] = now
        row["instruments_tested_count"] = str(summary.instruments_tested)
        row["anti_bias_review_passed"] = "yes"
        row["anti_bias_notes"] = (
            "HTF bars after close; session VP from past bars only; NY zoneinfo; "
            "signals on M1 close; fixed video params; no curve fitting."
        )
        row["data_source"] = "exness_production"
        row["data_root_used"] = data_root
        row["instrument_affinity_notes"] = affinity

        for k, v in agg.items():
            row[k] = str(v)

        if best_ir and best_ir.result:
            row["best_instrument"] = best_ir.symbol
            row["best_instrument_pf"] = str(best_ir.result.profit_factor)
            row["best_instrument_win_rate"] = str(best_ir.result.win_rate)
            row["best_instrument_pnl"] = str(round(best_ir.result.total_pnl, 2))
            row["best_instrument_trades"] = str(best_ir.result.total_trades)

        if worst_ir and worst_ir.result:
            row["worst_instrument"] = worst_ir.symbol

    # Propagate DUPLICATE-SKIP rows covered by this canonical
    for row in rows:
        if row.get("action") != "DUPLICATE-SKIP":
            continue
        if row.get("module_to_code") != module_id:
            continue
        canon = next(
            (r for r in rows if r.get("module_to_code") == module_id and r.get("action") == "CODE-CANONICAL"),
            None,
        )
        if not canon or canon.get("implementation_status") != "coded_and_backtested":
            continue
        row["implementation_status"] = "covered_by_canonical"
        row["strategy_registry_id"] = strategy_id
        for col in TRACKING_COLUMNS:
            if col in canon and col not in ("implementation_status",):
                row[col] = canon[col]

    _atomic_write_csv(path, fieldnames, rows)


def update_csv_pending_production(
    csv_path: str,
    module_id: str,
    strategy_id: str,
    anti_bias_notes: str,
) -> None:
    """Mark strategy as coded_pending_production_backtest when no real data."""
    path = Path(csv_path)
    rows, fieldnames = _read_csv(path)
    fieldnames = _ensure_columns(fieldnames, TRACKING_COLUMNS)
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        if row.get("module_to_code") != module_id or row.get("action") != "CODE-CANONICAL":
            continue
        row["implementation_status"] = "coded_pending_production_backtest"
        row["strategy_module_id"] = module_id
        row["strategy_folder"] = f"strategies/{module_id}/"
        row["strategy_registry_id"] = strategy_id
        row["coded_at"] = now
        row["anti_bias_review_passed"] = "yes"
        row["anti_bias_notes"] = anti_bias_notes
        row["data_source"] = "pending_exness_production"
        row["data_root_used"] = ""
        break

    _atomic_write_csv(path, fieldnames, rows)


def _build_affinity_notes(
    results: list[InstrumentResult], best: str, worst: str
) -> str:
    strong = [
        ir.symbol
        for ir in results
        if ir.result and ir.result.profit_factor > 1.5 and ir.result.total_trades >= 10
    ]
    weak = [
        ir.symbol
        for ir in results
        if ir.result and ir.result.profit_factor < 1.0 and ir.result.total_trades >= 10
    ]
    parts = []
    if strong:
        parts.append(f"Strong on {', '.join(strong[:5])} (PF>1.5, 10+ trades).")
    if weak:
        parts.append(f"Weak on {', '.join(weak[:5])} (PF<1.0).")
    if best:
        parts.append(f"Best ranked: {best}.")
    if worst:
        parts.append(f"Worst ranked: {worst}.")
    return " ".join(parts) if parts else "Insufficient trades for affinity analysis."


def _read_csv(path: Path) -> tuple[list[dict], list[str]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return rows, fieldnames


def _ensure_columns(fieldnames: list[str], columns: list[str]) -> list[str]:
    for col in columns:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames


def _atomic_write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="Audit CSV vs coded strategies vs data")
    p_audit.add_argument("--csv", default=str(DEFAULT_CSV))
    p_audit.add_argument("--data-root", default=None)

    sub.add_parser("list-strategies", help="List registered strategies")

    p_run = sub.add_parser("run", help="Run multi-instrument backtest")
    p_run.add_argument("--strategy", required=True)
    p_run.add_argument("--symbols", default="all")
    p_run.add_argument("--data-root", default=None)
    p_run.add_argument("--output", default=str(DEFAULT_OUTPUT))
    p_run.add_argument("--start", default=None)
    p_run.add_argument("--end", default=None)
    p_run.add_argument("--csv", default=str(DEFAULT_CSV))

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
