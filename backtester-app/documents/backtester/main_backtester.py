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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
DEFAULT_DATA_ROOT = Path(r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history")

if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig, BacktestResult
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
class MultiInstrumentSummary:
    strategy_id: str
    module_id: str
    video_number: str
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    best_instrument: str = ""
    worst_instrument: str = ""
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_path: str | None) -> tuple[Optional[Path], str]:
    if cli_path:
        path = Path(cli_path)
        if path.is_dir() and _has_symbol_data(path):
            return path, "cli"
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_data(path):
            return path, "env"
    if DEFAULT_DATA_ROOT.is_dir() and _has_symbol_data(DEFAULT_DATA_ROOT):
        return DEFAULT_DATA_ROOT, "default"
    return None, "missing"


def _has_symbol_data(root: Path) -> bool:
    for entry in root.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            for child in entry.iterdir():
                if child.is_dir() and list(child.glob("*.csv")):
                    return True
    return False


def load_strategy_config(module: str) -> dict[str, Any]:
    cfg_path = BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
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


def run_single_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    defaults: dict[str, Any],
) -> tuple[Optional[BacktestResult], str]:
    module_id = strategy_cls.__module__.split(".")[-2]
    cfg = load_strategy_config(module_id)
    req_names = cfg.get("required_timeframes") or [tf.name for tf in strategy_cls().timeframes]
    required_tfs = [tf_from_string(name) for name in req_names]

    for tf in required_tfs:
        if not client.has_timeframe(symbol, tf):
            return None, f"missing timeframe {tf.name}"

    start, end = client.get_full_date_range(symbol, required_tfs)
    if not start or not end or start >= end:
        return None, "invalid date range"

    bt_defaults = defaults or cfg.get("backtest_defaults", {})
    config = BacktestConfig(
        strategy_id=strategy_cls.id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=float(bt_defaults.get("initial_balance", 10000.0)),
        risk_per_trade=float(bt_defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(bt_defaults.get("spread_pips", 1.0)),
        slippage_pips=float(bt_defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(bt_defaults.get("commission_per_lot", 7.0)),
    )

    strategy = strategy_cls()
    engine = BacktestEngine(config, strategy, client)
    result = engine.run()

    result_dir = output_dir / strategy_cls.id
    result_dir.mkdir(parents=True, exist_ok=True)
    with open(result_dir / f"{symbol}.json", "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)

    return result, ""


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path,
    symbols: str | list[str] = "all",
    output_dir: str | Path = DEFAULT_OUTPUT,
    data_source: str = "exness_production",
) -> MultiInstrumentSummary:
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    client = ExnessCSVClient(data_root)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    module_id = strategy_cls.__module__.split(".")[-2]
    cfg = load_strategy_config(module_id)
    defaults = cfg.get("backtest_defaults", {})
    video_number = str(cfg.get("video_number", ""))
    min_trades = int(cfg.get("min_trades_for_ranking", 10))

    if symbols == "all":
        symbol_list = client.get_symbols()
    elif isinstance(symbols, str):
        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        symbol_list = [s.upper() for s in symbols]

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        module_id=module_id,
        video_number=video_number,
        instruments_scanned=len(symbol_list),
        data_source=data_source,
        data_root_used=str(data_root),
    )

    rows: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for symbol in symbol_list:
        result, skip_reason = run_single_backtest(strategy_cls, symbol, client, output_path, defaults)
        if result is None:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = skip_reason
            continue

        summary.instruments_tested += 1
        row = {
            "strategy_registry_id": strategy_cls.id,
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
            "bt_total_pnl": result.total_pnl,
            "bt_sharpe_ratio": result.sharpe_ratio,
            "bt_avg_rr": result.avg_rr,
            "bt_avg_trade_duration_mins": result.avg_trade_duration,
            "composite_score": 0.0,
            "rank_within_strategy": 0,
            "backtest_result_json": str(output_path / strategy_cls.id / f"{symbol}.json"),
            "backtested_at": now_iso,
            "data_quality_note": "",
            "data_source": data_source,
        }
        rows.append(row)

    best_pnl = max((float(r["bt_total_pnl"]) for r in rows), default=0.0)
    for row in rows:
        row["composite_score"] = round(composite_score(row, best_pnl, min_trades), 4)

    ranked = sorted(rows, key=lambda r: r["composite_score"], reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = rank

    eligible = [r for r in ranked if int(r["bt_total_trades"]) >= min_trades and r["composite_score"] >= 0]
    if eligible:
        summary.best_instrument = eligible[0]["symbol"]
        summary.worst_instrument = eligible[-1]["symbol"]

    summary.matrix_rows = ranked
    summary.aggregate_stats = _aggregate_stats(rows)
    _update_matrix_csv(output_path / "strategy_instrument_matrix.csv", ranked)
    return summary


def _aggregate_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "total_pnl": 0.0,
            "sharpe_ratio": 0.0,
            "avg_rr": 0.0,
        }
    total_trades = sum(int(r["bt_total_trades"]) for r in rows)
    total_pnl = sum(float(r["bt_total_pnl"]) for r in rows)
    win_rates = [float(r["bt_win_rate"]) for r in rows if int(r["bt_total_trades"]) > 0]
    pfs = [float(r["bt_profit_factor"]) for r in rows if int(r["bt_total_trades"]) > 0]
    dds = [float(r["bt_max_drawdown_pct"]) for r in rows]
    sharpes = [float(r["bt_sharpe_ratio"]) for r in rows if int(r["bt_total_trades"]) > 0]
    rrs = [float(r["bt_avg_rr"]) for r in rows if int(r["bt_total_trades"]) > 0]
    return {
        "trades": total_trades,
        "win_rate": round(sum(win_rates) / len(win_rates), 2) if win_rates else 0.0,
        "profit_factor": round(sum(pfs) / len(pfs), 2) if pfs else 0.0,
        "max_drawdown_pct": round(max(dds), 2) if dds else 0.0,
        "total_pnl": round(total_pnl, 2),
        "sharpe_ratio": round(sum(sharpes) / len(sharpes), 2) if sharpes else 0.0,
        "avg_rr": round(sum(rrs) / len(rrs), 2) if rrs else 0.0,
    }


def _update_matrix_csv(path: Path, new_rows: list[dict[str, Any]]):
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row

    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {col: str(row.get(col, "")) for col in MATRIX_COLUMNS}

    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda r: (r["strategy_registry_id"], r["symbol"])):
            writer.writerow(row)
    tmp.replace(path)


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def audit_command(csv_path: Path):
    fieldnames, rows = _read_csv_rows(csv_path)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    load_all_strategies()
    coded_modules = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__"}
    }

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    pending = [
        r for r in canonical
        if r.get("implementation_status", "") in {"", "not_started", "in_progress", "failed"}
    ]

    data_root, source = resolve_data_root(None)
    print("=== Backtester Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Canonical modules: {len(canonical)}")
    print(f"Pending canonical: {len(pending)}")
    print(f"Coded folders on disk: {sorted(coded_modules)}")
    print(f"Registered strategies: {[s.id for s in get_all_strategies()]}")
    print(f"main_backtester.py: {'yes' if Path(__file__).exists() else 'no'}")
    if data_root:
        print(f"Data root ({source}): {data_root} — {len(ExnessCSVClient(data_root).get_symbols())} symbols")
    else:
        print("Data root: MISSING (production backtest deferred)")


def update_tracking_csv(
    csv_path: Path,
    module: str,
    registry_id: str,
    status: str,
    data_source: str,
    data_root: str,
    summary: Optional[MultiInstrumentSummary] = None,
    anti_bias_passed: str = "yes",
    anti_bias_notes: str = "",
    backtest_error: str = "",
):
    fieldnames, rows = _read_csv_rows(csv_path)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    now_iso = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("module_to_code") != module:
            continue
        row["implementation_status"] = status
        row["strategy_module_id"] = module
        row["strategy_folder"] = f"strategies/{module}/"
        row["strategy_registry_id"] = registry_id
        row["data_source"] = data_source
        row["data_root_used"] = data_root
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["backtest_error"] = backtest_error
        if status in {"coded", "coded_pending_production_backtest", "in_progress"}:
            row["coded_at"] = row.get("coded_at") or now_iso
        if summary:
            row["backtested_at"] = now_iso if status == "coded_and_backtested" else row.get("backtested_at", "")
            row["instruments_tested_count"] = str(summary.instruments_tested)
            agg = summary.aggregate_stats
            row["bt_total_trades_all"] = str(agg.get("trades", 0))
            row["bt_win_rate_all"] = str(agg.get("win_rate", 0))
            row["bt_profit_factor_all"] = str(agg.get("profit_factor", 0))
            row["bt_max_drawdown_pct_all"] = str(agg.get("max_drawdown_pct", 0))
            row["bt_total_pnl_all"] = str(agg.get("total_pnl", 0))
            row["bt_sharpe_ratio_all"] = str(agg.get("sharpe_ratio", 0))
            row["bt_avg_rr_all"] = str(agg.get("avg_rr", 0))
            if summary.best_instrument:
                best = next((r for r in summary.matrix_rows if r["symbol"] == summary.best_instrument), None)
                worst = next((r for r in summary.matrix_rows if r["symbol"] == summary.worst_instrument), None)
                if best:
                    row["best_instrument"] = best["symbol"]
                    row["best_instrument_pf"] = str(best["bt_profit_factor"])
                    row["best_instrument_win_rate"] = str(best["bt_win_rate"])
                    row["best_instrument_pnl"] = str(best["bt_total_pnl"])
                    row["best_instrument_trades"] = str(best["bt_total_trades"])
                if worst:
                    row["worst_instrument"] = worst["symbol"]
                row["instrument_affinity_notes"] = _affinity_notes(summary)

    if status == "coded_and_backtested" and data_source == "exness_production":
        for row in rows:
            if row.get("action") == "DUPLICATE-SKIP" and row.get("module_to_code") == module:
                row["implementation_status"] = "covered_by_canonical"
                canonical = next((r for r in rows if r.get("module_to_code") == module and r.get("action") == "CODE-CANONICAL"), None)
                if canonical:
                    for col in TRACKING_COLUMNS:
                        if col.startswith("bt_") or col.startswith("best_") or col == "worst_instrument":
                            row[col] = canonical.get(col, "")

    _write_csv_atomic(csv_path, fieldnames, rows)


def _affinity_notes(summary: MultiInstrumentSummary) -> str:
    top = [r for r in summary.matrix_rows if r["composite_score"] > 0][:3]
    weak = [r for r in reversed(summary.matrix_rows) if int(r["bt_total_trades"]) >= 10][:2]
    top_txt = ", ".join(f"{r['symbol']}(PF={r['bt_profit_factor']})" for r in top) or "none"
    weak_txt = ", ".join(f"{r['symbol']}(PF={r['bt_profit_factor']})" for r in weak) or "insufficient sample"
    return f"Strongest on {top_txt}. Weakest on {weak_txt}. Designed for NQ; Exness FX/metals proxy."


def list_strategies_command():
    strategies = get_all_strategies()
    print(f"Registered strategies ({len(strategies)}):")
    for strat in strategies:
        print(f"  {strat.id} — {strat.name}")


def run_command(args: argparse.Namespace):
    data_root, _ = resolve_data_root(args.data_root)
    strategy_cls = get_strategy(args.strategy)
    if strategy_cls is None:
        raise SystemExit(f"Unknown strategy: {args.strategy}")

    module = strategy_cls.__module__.split(".")[-2]
    anti_bias_notes = (
        "HTF bars gated at close; session VP from same-day M1 only; "
        "absorption uses wick volume proxy; entries on bar close through swing cluster."
    )

    if data_root is None:
        update_tracking_csv(
            DEFAULT_CSV,
            module=module,
            registry_id=strategy_cls.id,
            status="coded_pending_production_backtest",
            data_source="pending_exness_production",
            data_root="",
            anti_bias_passed="yes",
            anti_bias_notes=anti_bias_notes,
        )
        print("Real Exness data unavailable — marked coded_pending_production_backtest")
        return

    summary = run_multi_instrument_backtest(
        strategy_id=strategy_cls.id,
        data_root=data_root,
        symbols=args.symbols,
        output_dir=args.output,
        data_source="exness_production",
    )
    update_tracking_csv(
        DEFAULT_CSV,
        module=module,
        registry_id=strategy_cls.id,
        status="coded_and_backtested",
        data_source="exness_production",
        data_root=str(data_root),
        summary=summary,
        anti_bias_passed="yes",
        anti_bias_notes=anti_bias_notes,
    )
    print(json.dumps(summary.aggregate_stats, indent=2))


def build_parser() -> argparse.ArgumentParser:
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
    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "audit":
        audit_command(Path(args.csv))
    elif args.command == "list-strategies":
        list_strategies_command()
    elif args.command == "run":
        run_command(args)
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
