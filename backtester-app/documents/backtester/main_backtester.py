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

import yaml

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig, BacktestResult
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies

BACKTESTER_ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = BACKTESTER_ROOT.parent / "video_docs" / "strategy_videos_90.csv"
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


@dataclass
class RunSummary:
    strategy_id: str
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
    best_stats: dict[str, Any] = field(default_factory=dict)
    worst_stats: dict[str, Any] = field(default_factory=dict)
    affinity_notes: str = ""


def resolve_data_root(cli_root: str | None = None) -> str | None:
    if cli_root:
        path = Path(cli_root)
        if path.is_dir() and _has_symbol_data(path):
            return str(path)
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path and Path(env_path).is_dir() and _has_symbol_data(Path(env_path)):
        return env_path
    if Path(WINDOWS_DEFAULT_DATA).is_dir() and _has_symbol_data(Path(WINDOWS_DEFAULT_DATA)):
        return WINDOWS_DEFAULT_DATA
    return None


def _has_symbol_data(root: Path) -> bool:
    for child in root.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            return True
    return False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def _write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        delete=False,
        dir=csv_path.parent,
    ) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        tmp_path = Path(tmp.name)
    tmp_path.replace(csv_path)


def _load_strategy_config(strategy_cls) -> dict[str, Any]:
    module = strategy_cls.__module__.split(".")[-1]
    config_path = BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _composite_score(row: dict[str, Any], max_pnl: float) -> float:
    pf = min(float(row.get("bt_profit_factor") or 0), 5) / 5 * 0.35
    wr = float(row.get("bt_win_rate") or 0) / 100 * 0.20
    sharpe = float(row.get("bt_sharpe_ratio") or 0)
    sharpe_norm = min(max(sharpe, -2), 3) / 3 * 0.20
    pnl = float(row.get("bt_total_pnl") or 0)
    pnl_norm = (pnl / max_pnl) * 0.15 if max_pnl > 0 else 0
    trades = min(int(row.get("bt_total_trades") or 0), 50) / 50 * 0.10
    return round(pf + wr + sharpe_norm + pnl_norm + trades, 4)


def _result_row(
    strategy_cls,
    symbol: str,
    result: BacktestResult,
    start: datetime,
    end: datetime,
    data_source: str,
    note: str = "",
) -> dict[str, Any]:
    config = _load_strategy_config(strategy_cls)
    return {
        "strategy_registry_id": strategy_cls.id,
        "strategy_module_id": config.get("module", ""),
        "video_number": str(config.get("video_number", "")),
        "symbol": symbol,
        "backtest_start_date": start.date().isoformat(),
        "backtest_end_date": end.date().isoformat(),
        "bt_total_trades": result.total_trades,
        "bt_winning_trades": result.winning_trades,
        "bt_losing_trades": result.losing_trades,
        "bt_win_rate": result.win_rate,
        "bt_profit_factor": result.profit_factor if result.profit_factor != float("inf") else 99.99,
        "bt_max_drawdown_pct": result.max_drawdown_pct,
        "bt_total_pnl": round(result.total_pnl, 2),
        "bt_sharpe_ratio": result.sharpe_ratio,
        "bt_avg_rr": result.avg_rr,
        "bt_avg_trade_duration_mins": result.avg_trade_duration,
        "composite_score": 0.0,
        "rank_within_strategy": 0,
        "backtest_result_json": "",
        "backtested_at": _utc_now_iso(),
        "data_quality_note": note,
        "data_source": data_source,
        "_result_obj": result,
    }


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> RunSummary:
    resolved_root = resolve_data_root(data_root)
    data_source = "exness_production" if resolved_root else "not_backtested"
    summary = RunSummary(
        strategy_id=strategy_id,
        data_root=resolved_root or (data_root or ""),
        data_source=data_source,
    )

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    config_yaml = _load_strategy_config(strategy_cls)
    defaults = config_yaml.get("backtest_defaults", {})
    required_tfs = [tf_from_string(t) for t in config_yaml.get("required_timeframes", [])]
    if not required_tfs:
        required_tfs = list(strategy_cls.timeframes)

    if not resolved_root:
        summary.affinity_notes = "Production backtest required on Windows with Exness history path."
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

    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)
    strategy_result_dir = output_path / strategy_cls.id
    strategy_result_dir.mkdir(parents=True, exist_ok=True)

    for symbol in target_symbols:
        if not client.symbol_has_timeframes(symbol, required_tfs):
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = f"missing timeframes: {[tf.name for tf in required_tfs]}"
            continue

        sym_start, sym_end = client.get_full_date_range(symbol, required_tfs)
        if sym_start is None or sym_end is None:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = "no date range"
            continue

        bt_start = start or sym_start
        bt_end = end or sym_end

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

        engine = BacktestEngine(bt_config, strategy_cls(), client)
        try:
            result = engine.run()
        except Exception as exc:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = str(exc)
            continue

        row = _result_row(strategy_cls, symbol, result, bt_start, bt_end, data_source)
        json_path = strategy_result_dir / f"{symbol}.json"
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle, indent=2)
        row["backtest_result_json"] = str(json_path)
        summary.matrix_rows.append(row)
        summary.instruments_tested += 1

    if summary.matrix_rows:
        max_pnl = max(float(r["bt_total_pnl"]) for r in summary.matrix_rows)
        for row in summary.matrix_rows:
            row["composite_score"] = _composite_score(row, max_pnl)

        ranked = sorted(summary.matrix_rows, key=lambda r: r["composite_score"], reverse=True)
        for rank, row in enumerate(ranked, start=1):
            row["rank_within_strategy"] = rank

        min_trades = int(config_yaml.get("min_trades_for_ranking", 10))
        eligible = [r for r in ranked if int(r["bt_total_trades"]) >= min_trades]
        if eligible:
            best = eligible[0]
            worst = eligible[-1]
            summary.best_instrument = best["symbol"]
            summary.worst_instrument = worst["symbol"]
            summary.best_stats = best
            summary.worst_stats = worst
            summary.affinity_notes = (
                f"Strong on {best['symbol']} (PF={best['bt_profit_factor']}, "
                f"{best['bt_total_trades']} trades). "
                f"Weak on {worst['symbol']} (PF={worst['bt_profit_factor']})."
            )

        trades = sum(int(r["bt_total_trades"]) for r in summary.matrix_rows)
        wins = sum(int(r["bt_winning_trades"]) for r in summary.matrix_rows)
        total_pnl = sum(float(r["bt_total_pnl"]) for r in summary.matrix_rows)
        gross_profit = sum(float(r["bt_total_pnl"]) for r in summary.matrix_rows if float(r["bt_total_pnl"]) > 0)
        gross_loss = abs(sum(float(r["bt_total_pnl"]) for r in summary.matrix_rows if float(r["bt_total_pnl"]) <= 0))
        summary.aggregate_stats = {
            "bt_total_trades_all": trades,
            "bt_win_rate_all": round(wins / trades * 100, 2) if trades else 0,
            "bt_profit_factor_all": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
            "bt_max_drawdown_pct_all": round(
                max(float(r["bt_max_drawdown_pct"]) for r in summary.matrix_rows), 2
            ),
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(
                sum(float(r["bt_sharpe_ratio"]) for r in summary.matrix_rows) / len(summary.matrix_rows), 2
            ),
            "bt_avg_rr_all": round(
                sum(float(r["bt_avg_rr"]) for r in summary.matrix_rows) / len(summary.matrix_rows), 2
            ),
        }

    _update_matrix_csv(output_path / "strategy_instrument_matrix.csv", summary.matrix_rows)
    return summary


def _update_matrix_csv(matrix_path: Path, new_rows: list[dict[str, Any]]):
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if matrix_path.exists():
        with open(matrix_path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for row in new_rows:
        clean = {k: v for k, v in row.items() if not k.startswith("_")}
        key = (clean["strategy_registry_id"], clean["symbol"])
        existing[key] = {k: str(clean.get(k, "")) for k in MATRIX_COLUMNS}

    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        delete=False,
        dir=matrix_path.parent,
    ) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        for row in existing.values():
            writer.writerow({k: row.get(k, "") for k in MATRIX_COLUMNS})
        tmp_path = Path(tmp.name)
    tmp_path.replace(matrix_path)


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    fieldnames, rows = _load_csv_rows(csv_path)
    load_all_strategies()
    coded_modules = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__", "tests"}
        and (p / "strategy.py").exists()
    }
    data_root = resolve_data_root(args.data_root)
    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")
    print(f"Backtester root: {BACKTESTER_ROOT}")
    print(f"Strategy folders on disk: {sorted(coded_modules)}")
    print(f"Registered strategies: {[s.id for s in get_all_strategies()]}")
    print(f"Data root: {data_root or 'UNAVAILABLE'}")
    if data_root:
        client = ExnessCSVClient(data_root)
        print(f"Symbols available: {len(client.get_symbols())}")
    print(f"Canonical progress: {done}/{len(canonical)}")
    pending = [
        r for r in canonical
        if r.get("implementation_status", "") in ("", "not_started", "in_progress", "failed")
    ]
    if pending:
        nxt = min(pending, key=lambda r: int(r["video_number"]))
        print(f"Next pending: Video #{nxt['video_number']} — {nxt['title']} ({nxt['module_to_code']})")
    else:
        print("All canonical modules marked coded_and_backtested.")
    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
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
    print(json.dumps({
        "strategy_id": summary.strategy_id,
        "data_root": summary.data_root,
        "data_source": summary.data_source,
        "instruments_scanned": summary.instruments_scanned,
        "instruments_tested": summary.instruments_tested,
        "instruments_skipped": summary.instruments_skipped,
        "best_instrument": summary.best_instrument,
        "worst_instrument": summary.worst_instrument,
        "aggregate_stats": summary.aggregate_stats,
        "affinity_notes": summary.affinity_notes,
    }, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit.add_argument("--csv", default=str(DEFAULT_CSV))
    audit.add_argument("--data-root", default=None)
    audit.set_defaults(func=cmd_audit)

    listing = sub.add_parser("list-strategies", help="List registered strategies")
    listing.set_defaults(func=cmd_list_strategies)

    run = sub.add_parser("run", help="Run multi-instrument backtest")
    run.add_argument("--strategy", required=True)
    run.add_argument("--symbols", default="all")
    run.add_argument("--data-root", default=None)
    run.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run.add_argument("--start", default=None)
    run.add_argument("--end", default=None)
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
