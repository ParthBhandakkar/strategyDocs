#!/usr/bin/env python3
"""
Main backtester CLI — audit, list strategies, run multi-instrument backtests.
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

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig, BacktestResult
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import (
    get_all_strategies,
    get_strategy,
    get_strategy_by_module,
    list_strategy_ids,
    load_all_strategies,
)

DEFAULT_WINDOWS_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
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


@dataclass
class InstrumentResult:
    symbol: str
    result: BacktestResult
    composite_score: float = 0.0
    rank: int = 0
    data_quality_note: str = ""
    skipped: bool = False


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    data_root: str
    data_source: str
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    instrument_results: list[InstrumentResult] = field(default_factory=list)
    best_instrument: str = ""
    worst_instrument: str = ""
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    affinity_notes: str = ""
    error: str = ""


def _backtester_root() -> Path:
    return Path(__file__).resolve().parent


def resolve_data_root(cli_path: str | None = None) -> Path | None:
    if cli_path:
        path = Path(cli_path)
        if path.is_dir() and _has_symbol_folders(path):
            return path
        return None

    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_folders(path):
            return path

    windows_default = Path(DEFAULT_WINDOWS_DATA_ROOT)
    if windows_default.is_dir() and _has_symbol_folders(windows_default):
        return windows_default

    return None


def _has_symbol_folders(path: Path) -> bool:
    for child in path.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            tf_dirs = [p for p in child.iterdir() if p.is_dir()]
            if tf_dirs:
                return True
    return False


def _load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = _backtester_root() / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _resolve_strategy(strategy_arg: str):
    load_all_strategies()
    strat = get_strategy(strategy_arg)
    if strat is None:
        strat = get_strategy_by_module(strategy_arg)
    if strat is None:
        raise ValueError(f"Strategy not found: {strategy_arg}")
    return strat


def _required_timeframes(strategy_cls, config: dict[str, Any]) -> list[TF]:
    if config.get("required_timeframes"):
        return [tf_from_string(tf) for tf in config["required_timeframes"]]
    return list(strategy_cls.timeframes)


def _composite_score(row: dict[str, Any], best_pnl: float, min_trades: int) -> float:
    trades = int(row.get("bt_total_trades") or 0)
    if trades < min_trades:
        return -1.0
    pf = min(float(row.get("bt_profit_factor") or 0), 5.0)
    win_rate = float(row.get("bt_win_rate") or 0)
    sharpe = float(row.get("bt_sharpe_ratio") or 0)
    pnl = float(row.get("bt_total_pnl") or 0)
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


def _result_row(
    strategy_id: str,
    module_id: str,
    video_number: str,
    symbol: str,
    result: BacktestResult,
    data_source: str,
    note: str = "",
) -> dict[str, Any]:
    return {
        "strategy_registry_id": strategy_id,
        "strategy_module_id": module_id,
        "video_number": video_number,
        "symbol": symbol,
        "backtest_start_date": result.config.start_date.date().isoformat(),
        "backtest_end_date": result.config.end_date.date().isoformat(),
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
        "composite_score": 0.0,
        "rank_within_strategy": 0,
        "backtest_result_json": "",
        "backtested_at": datetime.now(timezone.utc).isoformat(),
        "data_quality_note": note,
        "data_source": data_source,
    }


def _save_symbol_json(output_dir: Path, strategy_id: str, symbol: str, result: BacktestResult):
    out = output_dir / strategy_id / f"{symbol}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2)


def _read_matrix(matrix_path: Path) -> list[dict[str, str]]:
    if not matrix_path.exists():
        return []
    with open(matrix_path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_matrix(matrix_path: Path, rows: list[dict[str, Any]]):
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = matrix_path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    tmp.replace(matrix_path)


def _upsert_matrix_rows(matrix_path: Path, new_rows: list[dict[str, Any]]):
    existing = _read_matrix(matrix_path)
    index = {(r["strategy_registry_id"], r["symbol"]): r for r in existing}
    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        stored = dict(row)
        json_path = (
            _backtester_root()
            / "results"
            / row["strategy_registry_id"]
            / f"{row['symbol']}.json"
        )
        stored["backtest_result_json"] = str(json_path)
        index[key] = stored
    _write_matrix(matrix_path, list(index.values()))


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    strategy_cls = _resolve_strategy(strategy_id)
    module_name = strategy_cls.__module__.split(".")[-2]
    config = _load_strategy_config(module_name)
    defaults = config.get("backtest_defaults", {})
    min_trades = int(config.get("min_trades_for_ranking", 10))
    video_number = str(config.get("video_number", strategy_cls.source_video))

    resolved_root = resolve_data_root(str(data_root) if data_root else None)
    output_path = Path(output_dir or _backtester_root() / "results")
    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_name,
        video_number=video_number,
        data_root=str(resolved_root) if resolved_root else "",
        data_source="not_backtested" if resolved_root is None else "exness_production",
    )

    if resolved_root is None:
        summary.error = "No real Exness history path available"
        return summary

    client = ExnessCSVClient(resolved_root)
    all_symbols = client.get_symbols()
    summary.instruments_scanned = len(all_symbols)

    if isinstance(symbols, str):
        if symbols.lower() == "all":
            target_symbols = all_symbols
        else:
            target_symbols = [s.strip().upper() for s in symbols.split(",")]
    else:
        target_symbols = [s.upper() for s in symbols]

    required_tfs = _required_timeframes(strategy_cls, config)
    matrix_rows: list[dict[str, Any]] = []

    for symbol in target_symbols:
        if symbol not in all_symbols:
            summary.instruments_skipped += 1
            continue
        if not client.has_timeframes(symbol, required_tfs):
            summary.instruments_skipped += 1
            matrix_rows.append({
                **_result_row(
                    strategy_cls.id,
                    module_name,
                    video_number,
                    symbol,
                    BacktestResult(
                        config=BacktestConfig(
                            strategy_id=strategy_cls.id,
                            symbol=symbol,
                            start_date=datetime(2000, 1, 1),
                            end_date=datetime(2000, 1, 2),
                        )
                    ),
                    summary.data_source,
                    note=f"Missing required timeframes: {[tf.name for tf in required_tfs]}",
                ),
                "bt_total_trades": 0,
                "bt_winning_trades": 0,
                "bt_losing_trades": 0,
                "bt_win_rate": 0,
                "bt_profit_factor": 0,
                "bt_max_drawdown_pct": 0,
                "bt_total_pnl": 0,
                "bt_sharpe_ratio": 0,
                "bt_avg_rr": 0,
                "bt_avg_trade_duration_mins": 0,
            })
            continue

        sym_start, sym_end = client.get_full_date_range(symbol, required_tfs)
        if sym_start is None or sym_end is None:
            summary.instruments_skipped += 1
            continue

        bt_config = BacktestConfig(
            strategy_id=strategy_cls.id,
            symbol=symbol,
            start_date=start or sym_start,
            end_date=end or sym_end,
            initial_balance=float(defaults.get("initial_balance", 10000.0)),
            risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
            spread_pips=float(defaults.get("spread_pips", 1.0)),
            slippage_pips=float(defaults.get("slippage_pips", 0.5)),
            commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
        )

        strategy = strategy_cls()
        engine = BacktestEngine(bt_config, strategy, client)
        result = engine.run()
        row = _result_row(
            strategy_cls.id,
            module_name,
            video_number,
            symbol,
            result,
            summary.data_source,
        )
        matrix_rows.append(row)
        _save_symbol_json(output_path, strategy_cls.id, symbol, result)
        summary.instrument_results.append(
            InstrumentResult(symbol=symbol, result=result, data_quality_note="")
        )
        summary.instruments_tested += 1

    best_pnl = max((float(r["bt_total_pnl"]) for r in matrix_rows), default=0.0)
    for row in matrix_rows:
        row["composite_score"] = _composite_score(row, best_pnl, min_trades)

    ranked = sorted(
        [r for r in matrix_rows if int(r["bt_total_trades"]) >= min_trades],
        key=lambda r: r["composite_score"],
        reverse=True,
    )
    for idx, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = idx

    if ranked:
        best = ranked[0]
        worst = ranked[-1]
        summary.best_instrument = best["symbol"]
        summary.worst_instrument = worst["symbol"]
        strong = [r for r in ranked if float(r["bt_profit_factor"]) >= 1.0][:3]
        weak = [r for r in reversed(ranked) if float(r["bt_profit_factor"]) < 1.0][:3]
        parts = []
        if strong:
            parts.append(
                "Strong on "
                + ", ".join(
                    f"{r['symbol']} (PF={r['bt_profit_factor']}, {r['bt_total_trades']} trades)"
                    for r in strong
                )
            )
        if weak:
            parts.append(
                "Weak on "
                + ", ".join(
                    f"{r['symbol']} (PF={r['bt_profit_factor']}, {r['bt_total_trades']} trades)"
                    for r in weak
                )
            )
        summary.affinity_notes = ". ".join(parts) if parts else "Insufficient trade sample across symbols."

    total_trades = sum(int(r["bt_total_trades"]) for r in matrix_rows)
    total_pnl = sum(float(r["bt_total_pnl"]) for r in matrix_rows)
    win_rates = [float(r["bt_win_rate"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]
    pfs = [float(r["bt_profit_factor"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]
    dds = [float(r["bt_max_drawdown_pct"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]
    sharpes = [float(r["bt_sharpe_ratio"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]
    rrs = [float(r["bt_avg_rr"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]

    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    summary.aggregate_stats = {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": _avg(win_rates),
        "bt_profit_factor_all": _avg(pfs),
        "bt_max_drawdown_pct_all": _avg(dds),
        "bt_total_pnl_all": round(total_pnl, 2),
        "bt_sharpe_ratio_all": _avg(sharpes),
        "bt_avg_rr_all": _avg(rrs),
    }
    summary.matrix_rows = matrix_rows
    _upsert_matrix_rows(output_path / "strategy_instrument_matrix.csv", matrix_rows)
    return summary


def _ensure_csv_columns(csv_path: Path) -> list[dict[str, str]]:
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    for row in rows:
        for col in TRACKING_COLUMNS:
            row.setdefault(col, "")

    tmp = csv_path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(csv_path)
    return rows


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    rows = _ensure_csv_columns(csv_path)
    load_all_strategies()
    coded_modules = {
        p.name
        for p in (_backtester_root() / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__"}
    }
    coded_modules -= {"base", "registry"}

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = [r for r in canonical if r.get("implementation_status") == "coded_and_backtested"]
    pending = [
        r for r in canonical
        if r.get("implementation_status", "") in ("", "not_started", "in_progress", "failed", "coded", "coded_pending_production_backtest")
    ]

    data_root = resolve_data_root(args.data_root)
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_root else 0

    print("=== Backtester Audit ===")
    print(f"Backtester root: {_backtester_root()}")
    print(f"main_backtester.py: exists")
    print(f"Registered strategies: {list_strategy_ids()}")
    print(f"Coded folders: {sorted(coded_modules)}")
    print(f"Canonical modules: {len(canonical)} | done: {len(done)} | pending: {len(pending)}")
    print(f"Data root: {data_root or 'UNAVAILABLE'} ({symbol_count} symbols)")
    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    load_all_strategies()
    for strat in get_all_strategies():
        print(f"{strat.id}\t{strat.name}\tvideo={strat.source_video}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    if summary.error:
        print(f"Backtest skipped: {summary.error}")
        return 1
    print(f"Tested {summary.instruments_tested}/{summary.instruments_scanned} symbols")
    if summary.best_instrument:
        print(f"Best: {summary.best_instrument} | Worst: {summary.worst_instrument}")
    print(f"Aggregate PnL: {summary.aggregate_stats.get('bt_total_pnl_all')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit.add_argument("--csv", required=True)
    audit.add_argument("--data-root", default=None)

    listing = sub.add_parser("list-strategies", help="List registered strategies")
    listing.set_defaults(func=cmd_list_strategies)

    run = sub.add_parser("run", help="Run multi-instrument backtest")
    run.add_argument("--strategy", required=True)
    run.add_argument("--symbols", default="all")
    run.add_argument("--data-root", default=None)
    run.add_argument("--output", default=None)
    run.add_argument("--start", default=None)
    run.add_argument("--end", default=None)
    run.set_defaults(func=cmd_run)

    audit.set_defaults(func=cmd_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
