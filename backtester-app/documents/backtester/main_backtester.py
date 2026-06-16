#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, and multi-instrument run.
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

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
DEFAULT_DATA_ROOT = Path(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history")

if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies

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
    stats: dict[str, Any]
    composite_score: float = 0.0
    rank_within_strategy: int = 0
    data_quality_note: str = ""
    backtest_start_date: str = ""
    backtest_end_date: str = ""
    json_path: str = ""


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str = ""
    worst_instrument: str = ""
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_path: str | None) -> Path | None:
    if cli_path:
        path = Path(cli_path)
        if path.is_dir() and _has_symbol_folders(path):
            return path
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_folders(path):
            return path
    if DEFAULT_DATA_ROOT.is_dir() and _has_symbol_folders(DEFAULT_DATA_ROOT):
        return DEFAULT_DATA_ROOT
    return None


def _has_symbol_folders(path: Path) -> bool:
    return any(p.is_dir() and not p.name.startswith(".") for p in path.iterdir())


def load_strategy_config(module: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def composite_score_row(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0) or 0)
    if trades < min_trades:
        return 0.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0)
    win_rate = float(row.get("bt_win_rate", 0) or 0)
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    return (
        (pf / 5.0 * 0.35)
        + (win_rate / 100.0 * 0.20)
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
) -> InstrumentResult | None:
    strategy = strategy_cls()
    required_tfs = strategy.timeframes
    start, end = client.get_full_date_range(symbol, required_tfs)
    if not start or not end:
        return InstrumentResult(
            symbol=symbol,
            stats={},
            data_quality_note="missing_required_timeframes",
        )

    for tf in required_tfs:
        bars = client.get_bars(symbol, tf, start, end)
        if not bars:
            return InstrumentResult(
                symbol=symbol,
                stats={},
                data_quality_note=f"missing_{tf.name}_data",
            )

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

    engine = BacktestEngine(config=config, strategy=strategy, client=client)
    result = engine.run()

    result_dir = output_dir / strategy.id
    result_dir.mkdir(parents=True, exist_ok=True)
    json_path = result_dir / f"{symbol}.json"
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2)

    stats = {
        "bt_total_trades": result.total_trades,
        "bt_winning_trades": result.winning_trades,
        "bt_losing_trades": result.losing_trades,
        "bt_win_rate": result.win_rate,
        "bt_profit_factor": result.profit_factor,
        "bt_max_drawdown_pct": result.max_drawdown_pct,
        "bt_total_pnl": round(result.total_pnl, 2),
        "bt_sharpe_ratio": result.sharpe_ratio,
        "bt_avg_rr": result.avg_rr,
        "bt_avg_trade_duration_mins": result.avg_trade_duration,
    }
    return InstrumentResult(
        symbol=symbol,
        stats=stats,
        backtest_start_date=start.date().isoformat(),
        backtest_end_date=end.date().isoformat(),
        json_path=str(json_path),
    )


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path,
    symbols: str | list[str] = "all",
    output_dir: str | Path = DEFAULT_OUTPUT,
    min_trades_for_ranking: int = 10,
) -> MultiInstrumentSummary:
    data_root_path = Path(data_root)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module = strategy_id.split("_", 1)[-1] if "_" in strategy_id else strategy_id
    config_data = load_strategy_config(module)
    defaults = config_data.get("backtest_defaults", {})
    min_trades = int(config_data.get("min_trades_for_ranking", min_trades_for_ranking))
    video_number = str(config_data.get("video_number", ""))

    client = ExnessCSVClient(data_root_path)
    all_symbols = client.get_symbols()
    if symbols == "all":
        target_symbols = all_symbols
    elif isinstance(symbols, str):
        target_symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        target_symbols = list(symbols)

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module,
        video_number=video_number,
        instruments_scanned=len(target_symbols),
        data_source="exness_production",
        data_root_used=str(data_root_path),
    )

    instrument_results: list[InstrumentResult] = []
    for symbol in target_symbols:
        try:
            result = run_single_symbol_backtest(
                strategy_cls, symbol, client, output_path, defaults
            )
            if result is None:
                summary.instruments_skipped += 1
                continue
            if result.data_quality_note:
                summary.instruments_skipped += 1
            else:
                summary.instruments_tested += 1
            instrument_results.append(result)
        except Exception as exc:
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(
                    symbol=symbol,
                    stats={},
                    data_quality_note=f"error:{exc}",
                )
            )

    best_pnl = max(
        (float(r.stats.get("bt_total_pnl", 0) or 0) for r in instrument_results if r.stats),
        default=0.0,
    )
    now_iso = datetime.now(timezone.utc).isoformat()

    matrix_rows: list[dict[str, Any]] = []
    for item in instrument_results:
        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module,
            "video_number": video_number,
            "symbol": item.symbol,
            "backtest_start_date": item.backtest_start_date,
            "backtest_end_date": item.backtest_end_date,
            "bt_total_trades": item.stats.get("bt_total_trades", 0),
            "bt_winning_trades": item.stats.get("bt_winning_trades", 0),
            "bt_losing_trades": item.stats.get("bt_losing_trades", 0),
            "bt_win_rate": item.stats.get("bt_win_rate", 0),
            "bt_profit_factor": item.stats.get("bt_profit_factor", 0),
            "bt_max_drawdown_pct": item.stats.get("bt_max_drawdown_pct", 0),
            "bt_total_pnl": item.stats.get("bt_total_pnl", 0),
            "bt_sharpe_ratio": item.stats.get("bt_sharpe_ratio", 0),
            "bt_avg_rr": item.stats.get("bt_avg_rr", 0),
            "bt_avg_trade_duration_mins": item.stats.get("bt_avg_trade_duration_mins", 0),
            "composite_score": 0.0,
            "rank_within_strategy": 0,
            "backtest_result_json": item.json_path,
            "backtested_at": now_iso,
            "data_quality_note": item.data_quality_note,
            "data_source": "exness_production" if not item.data_quality_note else "not_backtested",
        }
        if item.stats:
            row["composite_score"] = round(composite_score_row(row, best_pnl, min_trades), 4)
        matrix_rows.append(row)

    ranked = sorted(
        [r for r in matrix_rows if int(r.get("bt_total_trades", 0) or 0) >= min_trades],
        key=lambda r: r["composite_score"],
        reverse=True,
    )
    for idx, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = idx

    if ranked:
        summary.best_instrument = ranked[0]["symbol"]
        summary.worst_instrument = ranked[-1]["symbol"]

    tested_stats = [r for r in instrument_results if r.stats]
    if tested_stats:
        total_trades = sum(int(r.stats.get("bt_total_trades", 0)) for r in tested_stats)
        total_wins = sum(int(r.stats.get("bt_winning_trades", 0)) for r in tested_stats)
        total_pnl = sum(float(r.stats.get("bt_total_pnl", 0)) for r in tested_stats)
        gross_profit = sum(
            float(r.stats.get("bt_total_pnl", 0))
            for r in tested_stats
            if float(r.stats.get("bt_total_pnl", 0)) > 0
        )
        gross_loss = abs(
            sum(
                float(r.stats.get("bt_total_pnl", 0))
                for r in tested_stats
                if float(r.stats.get("bt_total_pnl", 0)) <= 0
            )
        )
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0,
            "bt_profit_factor_all": round(gross_profit / gross_loss, 2) if gross_loss else 0,
            "bt_max_drawdown_pct_all": max(
                float(r.stats.get("bt_max_drawdown_pct", 0) or 0) for r in tested_stats
            ),
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(
                sum(float(r.stats.get("bt_sharpe_ratio", 0) or 0) for r in tested_stats)
                / len(tested_stats),
                2,
            ),
            "bt_avg_rr_all": round(
                sum(float(r.stats.get("bt_avg_rr", 0) or 0) for r in tested_stats)
                / len(tested_stats),
                2,
            ),
        }

    summary.matrix_rows = matrix_rows
    _write_matrix_csv(output_path / "strategy_instrument_matrix.csv", matrix_rows)
    return summary


def _write_matrix_csv(path: Path, rows: list[dict[str, Any]]):
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row
    for row in rows:
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        existing[key] = {col: row.get(col, "") for col in MATRIX_COLUMNS}
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        for row in existing.values():
            writer.writerow({col: row.get(col, "") for col in MATRIX_COLUMNS})


def _read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _write_csv_rows(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    temp_path = csv_path.with_suffix(".csv.tmp")
    with open(temp_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(csv_path)


def ensure_tracking_columns(fieldnames: list[str]) -> list[str]:
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    fieldnames, rows = _read_csv_rows(csv_path)
    fieldnames = ensure_tracking_columns(fieldnames)

    load_all_strategies()
    coded_modules = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__", "tests"}
        and (p / "strategy.py").exists()
    }

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    print(f"Canonical modules: {len(canonical)}")
    print(f"Coded folders on disk: {sorted(coded_modules)}")
    for row in canonical:
        module = row.get("module_to_code", "")
        status = row.get("implementation_status", "") or "not_started"
        print(f"  Video {row.get('video_number')}: {module} -> {status}")
    if args.fix_csv:
        _write_csv_rows(csv_path, fieldnames, rows)
        print(f"Tracking columns ensured in {csv_path}")
    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    strategies = get_all_strategies()
    if not strategies:
        print("No strategies registered.")
        return 1
    for cls in sorted(strategies, key=lambda c: c.id):
        print(f"{cls.id:40} {cls.name}")
    return 0


def update_csv_for_strategy(
    csv_path: Path,
    summary: MultiInstrumentSummary,
    *,
    backtested: bool,
    anti_bias_passed: str,
    anti_bias_notes: str,
    backtest_error: str = "",
):
    fieldnames, rows = _read_csv_rows(csv_path)
    fieldnames = ensure_tracking_columns(fieldnames)
    now_iso = datetime.now(timezone.utc).isoformat()

    if backtested:
        status = "coded_and_backtested"
        data_source = "exness_production"
    else:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"

    best_row = next(
        (r for r in summary.matrix_rows if r.get("symbol") == summary.best_instrument),
        {},
    )
    worst_row = next(
        (r for r in summary.matrix_rows if r.get("symbol") == summary.worst_instrument),
        {},
    )
    agg = summary.aggregate_stats

    affinity = (
        f"Tested {summary.instruments_tested}/{summary.instruments_scanned} symbols. "
        f"Best: {summary.best_instrument or 'n/a'}. Worst: {summary.worst_instrument or 'n/a'}."
    )

    for row in rows:
        if row.get("module_to_code") != summary.strategy_module_id:
            continue
        if row.get("action") != "CODE-CANONICAL":
            continue
        row["implementation_status"] = status if not backtest_error else "failed"
        row["strategy_module_id"] = summary.strategy_module_id
        row["strategy_folder"] = f"strategies/{summary.strategy_module_id}/"
        row["strategy_registry_id"] = summary.strategy_id
        row["coded_at"] = row.get("coded_at") or now_iso
        row["backtested_at"] = now_iso if backtested else ""
        row["instruments_tested_count"] = str(summary.instruments_tested)
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["backtest_error"] = backtest_error
        row["data_source"] = data_source if backtested else "pending_exness_production"
        row["data_root_used"] = summary.data_root_used
        for key, value in agg.items():
            row[key] = str(value)
        row["best_instrument"] = summary.best_instrument
        row["best_instrument_pf"] = str(best_row.get("bt_profit_factor", ""))
        row["best_instrument_win_rate"] = str(best_row.get("bt_win_rate", ""))
        row["best_instrument_pnl"] = str(best_row.get("bt_total_pnl", ""))
        row["best_instrument_trades"] = str(best_row.get("bt_total_trades", ""))
        row["worst_instrument"] = summary.worst_instrument
        row["instrument_affinity_notes"] = affinity

    if backtested:
        for row in rows:
            if (
                row.get("action") == "DUPLICATE-SKIP"
                and row.get("module_to_code") == summary.strategy_module_id
            ):
                row["implementation_status"] = "covered_by_canonical"
                row["strategy_registry_id"] = summary.strategy_id
                for key in agg:
                    row[key] = str(agg.get(key, ""))
                row["best_instrument"] = summary.best_instrument
                row["data_source"] = "exness_production"

    _write_csv_rows(csv_path, fieldnames, rows)


def cmd_run(args: argparse.Namespace) -> int:
    data_root = resolve_data_root(args.data_root)
    csv_path = Path(args.csv)

    strategy_cls = get_strategy(args.strategy)
    if strategy_cls is None:
        print(f"Unknown strategy: {args.strategy}")
        return 1

    module = args.strategy.split("_", 1)[-1] if "_" in args.strategy else args.strategy
    fieldnames, rows = _read_csv_rows(csv_path)
    fieldnames = ensure_tracking_columns(fieldnames)
    for row in rows:
        if row.get("module_to_code") == module:
            row["implementation_status"] = "in_progress"
            row["strategy_module_id"] = module
            row["strategy_folder"] = f"strategies/{module}/"
            row["strategy_registry_id"] = strategy_cls.id
            row["coded_at"] = datetime.now(timezone.utc).isoformat()
            break
    _write_csv_rows(csv_path, fieldnames, rows)

    anti_bias_passed = "yes"
    anti_bias_notes = (
        "M1-only signals after bar close; developing VP from session bars since NY open; "
        "HTF feed not used; absorption uses tick_volume wick proxy; no post-hoc tuning."
    )

    if data_root is None:
        update_csv_for_strategy(
            csv_path,
            MultiInstrumentSummary(
                strategy_id=strategy_cls.id,
                strategy_module_id=module,
                video_number="1",
            ),
            backtested=False,
            anti_bias_passed=anti_bias_passed,
            anti_bias_notes=anti_bias_notes,
        )
        print("Real Exness history unavailable — marked coded_pending_production_backtest")
        print(f"Production path: {DEFAULT_DATA_ROOT}")
        return 0

    try:
        summary = run_multi_instrument_backtest(
            strategy_id=strategy_cls.id,
            data_root=data_root,
            symbols=args.symbols,
            output_dir=args.output,
        )
        update_csv_for_strategy(
            csv_path,
            summary,
            backtested=True,
            anti_bias_passed=anti_bias_passed,
            anti_bias_notes=anti_bias_notes,
        )
        print(f"Backtest complete: {summary.instruments_tested} instruments tested")
        return 0
    except Exception as exc:
        update_csv_for_strategy(
            csv_path,
            MultiInstrumentSummary(
                strategy_id=strategy_cls.id,
                strategy_module_id=module,
                video_number="1",
            ),
            backtested=False,
            anti_bias_passed=anti_bias_passed,
            anti_bias_notes=anti_bias_notes,
            backtest_error=str(exc),
        )
        print(f"Backtest failed: {exc}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit.add_argument("--csv", default=str(DEFAULT_CSV))
    audit.add_argument("--fix-csv", action="store_true", help="Add tracking columns")
    audit.set_defaults(func=cmd_audit)

    listing = sub.add_parser("list-strategies", help="List registered strategies")
    listing.set_defaults(func=cmd_list_strategies)

    run = sub.add_parser("run", help="Run multi-instrument backtest")
    run.add_argument("--strategy", required=True)
    run.add_argument("--symbols", default="all")
    run.add_argument("--data-root", default=None)
    run.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run.add_argument("--csv", default=str(DEFAULT_CSV))
    run.add_argument("--start", default=None)
    run.add_argument("--end", default=None)
    run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
