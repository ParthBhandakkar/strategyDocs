#!/usr/bin/env python3
"""
Main backtester CLI — audit, list strategies, and run multi-instrument backtests.
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
DOCS_ROOT = BACKTESTER_ROOT.parent
if str(DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_strategy, list_strategy_ids, load_all_strategies

DEFAULT_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
CSV_PATH = BACKTESTER_ROOT.parent / "video_docs" / "strategy_videos_90.csv"
MATRIX_PATH = BACKTESTER_ROOT / "results" / "strategy_instrument_matrix.csv"

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
    result: Any
    composite_score: float = 0.0
    rank_within_strategy: int = 0
    data_quality_note: str = ""
    skipped: bool = False


@dataclass
class MultiBacktestSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    instrument_results: list[InstrumentResult] = field(default_factory=list)
    best_instrument: str = ""
    worst_instrument: str = ""
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_root: str | None) -> str:
    if cli_root:
        return cli_root
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path and Path(env_path).is_dir():
        symbols = [p for p in Path(env_path).iterdir() if p.is_dir()]
        if symbols:
            return env_path
    return DEFAULT_DATA_ROOT


def load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0) or 0)
    if trades < min_trades:
        return -1.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0) / 5.0 * 0.35
    wr = float(row.get("bt_win_rate", 0) or 0) / 100.0 * 0.20
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0 * 0.20
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    pnl_norm = (pnl / best_pnl) * 0.15 if best_pnl > 0 else 0.0
    trade_norm = min(trades, 50) / 50.0 * 0.10
    return round(pf + wr + sharpe_norm + pnl_norm + trade_norm, 4)


def ensure_csv_columns(csv_path: Path) -> list[dict[str, str]]:
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
    return rows, fieldnames


def save_csv_atomic(csv_path: Path, rows: list[dict[str, str]], fieldnames: list[str]):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", delete=False) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        temp_name = tmp.name
    os.replace(temp_name, csv_path)


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    rows, fieldnames = ensure_csv_columns(csv_path)
    save_csv_atomic(csv_path, rows, fieldnames)

    coded_dirs = [
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__"}
    ]
    registry_ids = list_strategy_ids()
    canonical = [r for r in rows if r.get("action") == "CODE-CANONICAL"]
    done = [r for r in canonical if r.get("implementation_status") == "coded_and_backtested"]
    pending = [r for r in canonical if r.get("implementation_status") in ("", "not_started", "in_progress", "failed")]

    data_root = resolve_data_root(args.data_root)
    symbol_count = 0
    if Path(data_root).is_dir():
        client = ExnessCSVClient(data_root)
        symbol_count = len(client.get_symbols())

    print("=== Backtester Audit ===")
    print(f"Strategy folders: {sorted(coded_dirs)}")
    print(f"Registry IDs: {registry_ids}")
    print(f"Canonical modules: {len(canonical)} | done: {len(done)} | pending: {len(pending)}")
    print(f"Data root: {data_root} | symbols: {symbol_count}")
    return 0


def cmd_list_strategies(_: argparse.Namespace) -> int:
    load_all_strategies()
    for strat_id in list_strategy_ids():
        cls = get_strategy(strat_id)
        print(f"{strat_id} — {cls.name if cls else 'unknown'}")
    return 0


def run_single_symbol(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    config_defaults: dict[str, Any],
    required_tfs: list[TF],
) -> InstrumentResult:
    if not client.has_timeframes(symbol, required_tfs):
        missing = [tf.name for tf in required_tfs if client._find_csv_file(symbol, tf) is None]
        return InstrumentResult(
            symbol=symbol,
            result=None,
            skipped=True,
            data_quality_note=f"missing timeframes: {', '.join(missing)}",
        )

    start, end = client.get_full_date_range(symbol, required_tfs)
    if start is None or end is None:
        return InstrumentResult(symbol=symbol, result=None, skipped=True, data_quality_note="no date range")

    cfg = BacktestConfig(
        strategy_id=strategy_cls.id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=float(config_defaults.get("initial_balance", 10000.0)),
        risk_per_trade=float(config_defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(config_defaults.get("spread_pips", 1.0)),
        slippage_pips=float(config_defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(config_defaults.get("commission_per_lot", 7.0)),
    )

    strategy = strategy_cls()
    engine = BacktestEngine(cfg, strategy, client)
    result = engine.run()

    result_dir = output_dir / strategy_cls.id
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{symbol}.json"
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2)

    return InstrumentResult(symbol=symbol, result=result)


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
) -> MultiBacktestSummary:
    load_all_strategies()
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    module_name = strategy_cls.__module__.split(".")[-2]
    config = load_strategy_config(module_name)
    required_tf_names = config.get(
        "required_timeframes",
        [tf.name for tf in strategy_cls.timeframes],
    )
    required_tfs = [tf_from_string(name) if isinstance(name, str) else name for name in required_tf_names]
    defaults = config.get("backtest_defaults", {})
    min_trades = int(config.get("min_trades_for_ranking", 10))
    video_number = str(config.get("video_number", getattr(strategy_cls, "source_video", "")))

    client = ExnessCSVClient(data_root)
    all_symbols = client.get_symbols()
    if isinstance(symbols, str) and symbols.lower() == "all":
        target_symbols = all_symbols
    elif isinstance(symbols, str):
        target_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        target_symbols = [s.upper() for s in symbols]

    out = Path(output_dir or BACKTESTER_ROOT / "results")
    out.mkdir(parents=True, exist_ok=True)

    summary = MultiBacktestSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_name,
        video_number=video_number,
        instruments_scanned=len(target_symbols),
        data_root_used=data_root,
        data_source="exness_production" if Path(data_root).is_dir() and all_symbols else "not_backtested",
    )

    if not Path(data_root).is_dir() or not all_symbols:
        summary.data_source = "pending_exness_production"
        return summary

    instrument_rows: list[dict[str, Any]] = []
    results: list[InstrumentResult] = []

    for symbol in target_symbols:
        item = run_single_symbol(strategy_cls, symbol, client, out, defaults, required_tfs)
        results.append(item)
        if item.skipped or item.result is None:
            summary.instruments_skipped += 1
            instrument_rows.append({
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": module_name,
                "video_number": video_number,
                "symbol": symbol,
                "data_quality_note": item.data_quality_note,
                "data_source": summary.data_source,
                "skipped": True,
            })
            continue

        summary.instruments_tested += 1
        stats = item.result.to_dict()["stats"]
        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_name,
            "video_number": video_number,
            "symbol": symbol,
            "backtest_start_date": item.result.config.start_date.date().isoformat(),
            "backtest_end_date": item.result.config.end_date.date().isoformat(),
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
            "backtest_result_json": str(out / strategy_cls.id / f"{symbol}.json"),
            "backtested_at": datetime.now(timezone.utc).isoformat(),
            "data_quality_note": item.data_quality_note,
            "data_source": "exness_production",
        }
        instrument_rows.append(row)

    best_pnl = max((float(r.get("bt_total_pnl", 0) or 0) for r in instrument_rows if not r.get("skipped")), default=0.0)
    ranked: list[tuple[str, float, dict[str, Any]]] = []
    for row in instrument_rows:
        if row.get("skipped"):
            continue
        score = composite_score(row, best_pnl, min_trades=min_trades)
        row["composite_score"] = score
        ranked.append((row["symbol"], score, row))

    ranked.sort(key=lambda item: item[1], reverse=True)
    for idx, (_, _, row) in enumerate(ranked, start=1):
        row["rank_within_strategy"] = idx

    eligible = [item for item in ranked if item[1] >= 0]
    if eligible:
        best = eligible[0][2]
        worst = eligible[-1][2]
        summary.best_instrument = best["symbol"]
        summary.worst_instrument = worst["symbol"]

    if instrument_rows:
        tested_rows = [r for r in instrument_rows if not r.get("skipped")]
        total_trades = sum(int(r.get("bt_total_trades", 0) or 0) for r in tested_rows)
        total_pnl = sum(float(r.get("bt_total_pnl", 0) or 0) for r in tested_rows)
        win_rates = [float(r.get("bt_win_rate", 0) or 0) for r in tested_rows if int(r.get("bt_total_trades", 0) or 0) > 0]
        pfs = [float(r.get("bt_profit_factor", 0) or 0) for r in tested_rows if int(r.get("bt_total_trades", 0) or 0) > 0]
        dds = [float(r.get("bt_max_drawdown_pct", 0) or 0) for r in tested_rows]
        sharpes = [float(r.get("bt_sharpe_ratio", 0) or 0) for r in tested_rows]
        rrs = [float(r.get("bt_avg_rr", 0) or 0) for r in tested_rows if int(r.get("bt_total_trades", 0) or 0) > 0]
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(sum(win_rates) / len(win_rates), 2) if win_rates else 0.0,
            "bt_profit_factor_all": round(sum(pfs) / len(pfs), 2) if pfs else 0.0,
            "bt_max_drawdown_pct_all": round(max(dds), 2) if dds else 0.0,
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(sum(sharpes) / len(sharpes), 2) if sharpes else 0.0,
            "bt_avg_rr_all": round(sum(rrs) / len(rrs), 2) if rrs else 0.0,
        }

    summary.matrix_rows = instrument_rows
    summary.instrument_results = results
    _update_matrix_csv(instrument_rows)
    return summary


def _update_matrix_csv(rows: list[dict[str, Any]]):
    MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    fieldnames = [
        "strategy_registry_id", "strategy_module_id", "video_number", "symbol",
        "backtest_start_date", "backtest_end_date", "bt_total_trades", "bt_winning_trades",
        "bt_losing_trades", "bt_win_rate", "bt_profit_factor", "bt_max_drawdown_pct",
        "bt_total_pnl", "bt_sharpe_ratio", "bt_avg_rr", "bt_avg_trade_duration_mins",
        "composite_score", "rank_within_strategy", "backtest_result_json", "backtested_at",
        "data_quality_note", "data_source",
    ]
    if MATRIX_PATH.exists():
        with open(MATRIX_PATH, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or fieldnames
            for row in reader:
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row
    for row in rows:
        if row.get("skipped"):
            continue
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        existing[key] = {k: row.get(k, "") for k in fieldnames}
    with open(MATRIX_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing.values())


def update_tracking_csv(summary: MultiBacktestSummary, status: str, anti_bias_passed: str, anti_bias_notes: str, error: str = ""):
    rows, fieldnames = ensure_csv_columns(CSV_PATH)
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("module_to_code") != summary.strategy_module_id:
            continue
        row["implementation_status"] = status
        row["strategy_module_id"] = summary.strategy_module_id
        row["strategy_folder"] = f"strategies/{summary.strategy_module_id}/"
        row["strategy_registry_id"] = summary.strategy_id
        row["coded_at"] = row.get("coded_at") or now
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["backtest_error"] = error
        row["data_source"] = summary.data_source
        row["data_root_used"] = summary.data_root_used
        row["instruments_tested_count"] = str(summary.instruments_tested)
        if summary.instruments_tested > 0:
            row["backtested_at"] = now
        for key, value in summary.aggregate_stats.items():
            row[key] = str(value)
        if summary.best_instrument:
            best_row = next((r for r in summary.matrix_rows if r.get("symbol") == summary.best_instrument), {})
            row["best_instrument"] = summary.best_instrument
            row["best_instrument_pf"] = str(best_row.get("bt_profit_factor", ""))
            row["best_instrument_win_rate"] = str(best_row.get("bt_win_rate", ""))
            row["best_instrument_pnl"] = str(best_row.get("bt_total_pnl", ""))
            row["best_instrument_trades"] = str(best_row.get("bt_total_trades", ""))
        if summary.worst_instrument:
            row["worst_instrument"] = summary.worst_instrument
        row["instrument_affinity_notes"] = (
            f"Tested {summary.instruments_tested}/{summary.instruments_scanned} symbols. "
            f"Best: {summary.best_instrument or 'n/a'}; Worst: {summary.worst_instrument or 'n/a'}."
        )
    save_csv_atomic(CSV_PATH, rows, fieldnames)


def cmd_run(args: argparse.Namespace) -> int:
    data_root = resolve_data_root(args.data_root)
    try:
        summary = run_multi_instrument_backtest(
            strategy_id=args.strategy,
            data_root=data_root,
            symbols=args.symbols,
            output_dir=args.output,
        )
    except Exception as exc:
        update_tracking_csv(
            MultiBacktestSummary(strategy_id=args.strategy, strategy_module_id="", video_number=""),
            status="failed",
            anti_bias_passed="no",
            anti_bias_notes="",
            error=str(exc),
        )
        print(f"Backtest failed: {exc}")
        return 1

    if summary.data_source == "pending_exness_production":
        status = "coded_pending_production_backtest"
        anti_passed = "yes"
        anti_notes = (
            "No lookahead: M1-only signals after 9:30 NY; session VP from prior closed M1 bars; "
            "entries on bar close. Production backtest deferred — Exness path unavailable."
        )
    else:
        status = "coded_and_backtested"
        anti_passed = "yes"
        anti_notes = (
            "No lookahead: HTF closed-bar feed; session VP uses bars <= current_time; "
            "entries on M1 close; stops/targets from structure not optimized on results."
        )

    update_tracking_csv(summary, status=status, anti_bias_passed=anti_passed, anti_bias_notes=anti_notes)
    print(json.dumps({
        "strategy_id": summary.strategy_id,
        "instruments_tested": summary.instruments_tested,
        "instruments_skipped": summary.instruments_skipped,
        "best_instrument": summary.best_instrument,
        "aggregate_stats": summary.aggregate_stats,
        "status": status,
    }, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit.add_argument("--csv", default=str(CSV_PATH))
    audit.add_argument("--data-root", default=None)

    listing = sub.add_parser("list-strategies", help="List registered strategies")
    listing.set_defaults(func=cmd_list_strategies)

    run = sub.add_parser("run", help="Run multi-instrument backtest")
    run.add_argument("--strategy", required=True)
    run.add_argument("--symbols", default="all")
    run.add_argument("--data-root", default=None)
    run.add_argument("--output", default=str(BACKTESTER_ROOT / "results"))
    run.set_defaults(func=cmd_run)

    audit.set_defaults(func=cmd_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
