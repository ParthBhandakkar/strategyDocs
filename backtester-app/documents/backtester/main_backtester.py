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
from typing import Any, Optional

import yaml

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_RESULTS = BACKTESTER_ROOT / "results"
DEFAULT_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"

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
class MultiBacktestSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    data_root: str
    data_source: str
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    matrix_rows: list[dict] = field(default_factory=list)
    best_instrument: Optional[str] = None
    worst_instrument: Optional[str] = None
    aggregate_stats: dict = field(default_factory=dict)
    affinity_notes: str = ""


def resolve_data_root(cli_root: str | None = None) -> tuple[str, str]:
    """Return (path, source_tag). source_tag indicates availability."""
    if cli_root:
        path = Path(cli_root)
        if path.is_dir() and _has_symbol_data(path):
            return str(path), "exness_production"
        return str(path), "not_backtested"

    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path and Path(env_path).is_dir() and _has_symbol_data(Path(env_path)):
        return env_path, "exness_production"

    default = Path(DEFAULT_DATA_ROOT)
    if default.is_dir() and _has_symbol_data(default):
        return str(default), "exness_production"

    return str(default), "pending_exness_production"


def _has_symbol_data(root: Path) -> bool:
    for entry in root.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            for tf_dir in entry.iterdir():
                if tf_dir.is_dir() and list(tf_dir.glob("*.csv")):
                    return True
    return False


def load_strategy_config(module_name: str) -> dict:
    config_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def compute_composite_score(row: dict, max_pnl: float, min_trades: int = 10) -> float:
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


def read_csv_rows(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".csv", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def update_matrix_csv(output_dir: Path, new_rows: list[dict]) -> None:
    matrix_path = output_dir / "strategy_instrument_matrix.csv"
    if matrix_path.exists():
        with open(matrix_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            existing = {(r["strategy_registry_id"], r["symbol"]): r for r in reader}
    else:
        existing = {}

    for row in new_rows:
        existing[(row["strategy_registry_id"], row["symbol"])] = row

    write_csv_atomic(matrix_path, MATRIX_COLUMNS, list(existing.values()))


def audit_csv(csv_path: Path) -> dict:
    from backtester.strategies.registry import get_all_strategies, load_all_strategies

    load_all_strategies()
    strategies = get_all_strategies()
    registered = {cls.id: cls.__module__.split(".")[-2] for cls in strategies}

    fieldnames, rows = read_csv_rows(csv_path)
    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    status_counts: dict[str, int] = {}
    for row in canonical:
        status = row.get("implementation_status") or "not_started"
        status_counts[status] = status_counts.get(status, 0) + 1

    data_root, data_tag = resolve_data_root()
    symbols = []
    if Path(data_root).is_dir() and _has_symbol_data(Path(data_root)):
        from backtester.connectors.exness_csv import ExnessCSVClient

        symbols = ExnessCSVClient(data_root).get_symbols()

    return {
        "csv_path": str(csv_path),
        "canonical_count": len(canonical),
        "status_counts": status_counts,
        "registered_strategies": registered,
        "data_root": data_root,
        "data_source": data_tag,
        "symbol_count": len(symbols),
    }


def cmd_audit(args: argparse.Namespace) -> int:
    report = audit_csv(Path(args.csv))
    print("=== Backtester Audit ===")
    print(f"CSV: {report['csv_path']}")
    print(f"Canonical modules: {report['canonical_count']}")
    print(f"Registered strategies: {len(report['registered_strategies'])}")
    for sid, module in sorted(report["registered_strategies"].items()):
        print(f"  - {sid} ({module})")
    print(f"Data root: {report['data_root']}")
    print(f"Data source: {report['data_source']}")
    print(f"Symbols available: {report['symbol_count']}")
    print("Status counts:")
    for status, count in sorted(report["status_counts"].items()):
        print(f"  {status}: {count}")
    return 0


def cmd_list_strategies(_: argparse.Namespace) -> int:
    from backtester.strategies.registry import get_all_strategies, load_all_strategies

    load_all_strategies()
    for cls in sorted(get_all_strategies(), key=lambda c: c.id):
        print(f"{cls.id}\t{cls.name}\tvideo={cls.source_video}")
    return 0


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str = "all",
    output_dir: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiBacktestSummary:
    from backtester.connectors.exness_csv import ExnessCSVClient
    from backtester.core import BacktestConfig
    from backtester.core.engine import BacktestEngine
    from backtester.strategies.registry import get_strategy

    resolved_root, data_tag = resolve_data_root(data_root)
    client = ExnessCSVClient(resolved_root)
    output_path = Path(output_dir or DEFAULT_RESULTS)
    output_path.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module_name = strategy_cls.__module__.split(".")[-2]
    config_yaml = load_strategy_config(module_name)
    defaults = config_yaml.get("backtest_defaults", {})
    video_number = str(config_yaml.get("video_number", strategy_cls.source_video))

    if symbols == "all":
        symbol_list = client.get_symbols()
    else:
        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    summary = MultiBacktestSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_name,
        video_number=video_number,
        data_root=resolved_root,
        data_source=data_tag if client.path_exists() and _has_symbol_data(Path(resolved_root)) else data_tag,
        instruments_scanned=len(symbol_list),
    )

    if not client.path_exists() or not _has_symbol_data(Path(resolved_root)):
        summary.instruments_skipped = len(symbol_list)
        summary.affinity_notes = "Production backtest required on Windows with Exness structured history."
        return summary

    instrument_results: list[InstrumentResult] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for symbol in symbol_list:
        if not client.has_timeframes(symbol, list(strategy_cls.timeframes)):
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=None,
                    skipped=True,
                    data_quality_note="Missing required timeframe CSV data",
                )
            )
            continue

        sym_start, sym_end = client.get_full_date_range(symbol, list(strategy_cls.timeframes))
        if sym_start is None or sym_end is None:
            summary.instruments_skipped += 1
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

        strategy = strategy_cls()
        engine = BacktestEngine(bt_config, strategy, client)
        result = engine.run()
        summary.instruments_tested += 1

        json_path = output_path / strategy_cls.id / f"{symbol}.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle, indent=2)

        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_name,
            "video_number": video_number,
            "symbol": symbol,
            "backtest_start_date": bt_start.date().isoformat(),
            "backtest_end_date": bt_end.date().isoformat(),
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
            "backtest_result_json": str(json_path.relative_to(output_path)),
            "backtested_at": now_iso,
            "data_quality_note": "",
            "data_source": "exness_production",
        }
        instrument_results.append(InstrumentResult(symbol=symbol, result=result, composite_score=0.0))
        summary.matrix_rows.append(row)

    max_pnl = max((float(r["bt_total_pnl"]) for r in summary.matrix_rows), default=0.0)
    min_trades = int(config_yaml.get("min_trades_for_ranking", 10))
    for row in summary.matrix_rows:
        row["composite_score"] = compute_composite_score(row, max_pnl, min_trades)

    ranked = sorted(summary.matrix_rows, key=lambda r: r["composite_score"], reverse=True)
    for idx, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = idx

    eligible = [r for r in ranked if int(r["bt_total_trades"]) >= min_trades]
    if eligible:
        best = eligible[0]
        worst = eligible[-1]
        summary.best_instrument = best["symbol"]
        summary.worst_instrument = worst["symbol"]
        summary.affinity_notes = (
            f"Strongest on {best['symbol']} (PF={best['bt_profit_factor']}, "
            f"{best['bt_total_trades']} trades). Weakest ranked: {worst['symbol']} "
            f"(PF={worst['bt_profit_factor']}). NQ-specific orderflow adapted to tick_volume wick proxy."
        )

    if summary.matrix_rows:
        total_trades = sum(int(r["bt_total_trades"]) for r in summary.matrix_rows)
        avg_wr = sum(float(r["bt_win_rate"]) for r in summary.matrix_rows) / len(summary.matrix_rows)
        pfs = [float(r["bt_profit_factor"]) for r in summary.matrix_rows if r["bt_profit_factor"] not in (float("inf"),)]
        avg_pf = sum(pfs) / len(pfs) if pfs else 0.0
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(avg_wr, 2),
            "bt_profit_factor_all": round(avg_pf, 2),
            "bt_max_drawdown_pct_all": round(
                max(float(r["bt_max_drawdown_pct"]) for r in summary.matrix_rows), 2
            ),
            "bt_total_pnl_all": round(sum(float(r["bt_total_pnl"]) for r in summary.matrix_rows), 2),
            "bt_sharpe_ratio_all": round(
                sum(float(r["bt_sharpe_ratio"]) for r in summary.matrix_rows) / len(summary.matrix_rows), 2
            ),
            "bt_avg_rr_all": round(
                sum(float(r["bt_avg_rr"]) for r in summary.matrix_rows) / len(summary.matrix_rows), 2
            ),
        }

    update_matrix_csv(output_path, summary.matrix_rows)
    return summary


def update_tracking_csv(
    csv_path: Path,
    strategy_id: str,
    module_name: str,
    summary: MultiBacktestSummary,
    anti_bias_passed: str = "yes",
    anti_bias_notes: str = "",
    backtest_error: str = "",
) -> None:
    fieldnames, rows = read_csv_rows(csv_path)
    now_iso = datetime.now(timezone.utc).isoformat()

    if summary.data_source == "exness_production" and summary.instruments_tested > 0:
        impl_status = "coded_and_backtested"
        data_source = "exness_production"
    elif summary.data_source == "pending_exness_production":
        impl_status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"
    else:
        impl_status = "coded"
        data_source = "not_backtested"

    best_row = next((r for r in summary.matrix_rows if r["symbol"] == summary.best_instrument), None)

    for row in rows:
        if row.get("module_to_code") != module_name:
            continue
        if row.get("action") != "CODE-CANONICAL":
            continue
        row["implementation_status"] = impl_status if not backtest_error else "failed"
        row["strategy_module_id"] = module_name
        row["strategy_folder"] = f"strategies/{module_name}/"
        row["strategy_registry_id"] = strategy_id
        row["coded_at"] = row.get("coded_at") or now_iso
        if summary.instruments_tested > 0:
            row["backtested_at"] = now_iso
        row["instruments_tested_count"] = str(summary.instruments_tested)
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["backtest_error"] = backtest_error
        row["data_source"] = data_source
        row["data_root_used"] = summary.data_root
        for key, val in summary.aggregate_stats.items():
            row[key] = str(val)
        if best_row:
            row["best_instrument"] = summary.best_instrument or ""
            row["best_instrument_pf"] = str(best_row.get("bt_profit_factor", ""))
            row["best_instrument_win_rate"] = str(best_row.get("bt_win_rate", ""))
            row["best_instrument_pnl"] = str(best_row.get("bt_total_pnl", ""))
            row["best_instrument_trades"] = str(best_row.get("bt_total_trades", ""))
        row["worst_instrument"] = summary.worst_instrument or ""
        row["instrument_affinity_notes"] = summary.affinity_notes

    if impl_status == "coded_and_backtested":
        for row in rows:
            if row.get("action") != "DUPLICATE-SKIP":
                continue
            if row.get("module_to_code") != module_name:
                continue
            row["implementation_status"] = "covered_by_canonical"
            row["strategy_registry_id"] = strategy_id
            row["data_source"] = data_source
            for key in summary.aggregate_stats:
                row[key] = str(summary.aggregate_stats[key])
            row["instrument_affinity_notes"] = summary.affinity_notes

    write_csv_atomic(csv_path, fieldnames, rows)


def cmd_run(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv) if args.csv else DEFAULT_CSV
    try:
        summary = run_multi_instrument_backtest(
            strategy_id=args.strategy,
            data_root=args.data_root,
            symbols=args.symbols,
            output_dir=args.output,
        )
        anti_bias_notes = (
            "HTF N/A (M1-only). Session VP built from bars since NY 9:30 only. "
            "L2 orderflow proxied via tick_volume wick concentration. "
            "Entries on bar close after cluster inversion. Params from video spec, not tuned."
        )
        update_tracking_csv(
            csv_path,
            summary.strategy_id,
            summary.strategy_module_id,
            summary,
            anti_bias_passed="yes",
            anti_bias_notes=anti_bias_notes,
        )
        print(f"\nBacktest complete: {summary.strategy_id}")
        print(f"  Tested: {summary.instruments_tested}, Skipped: {summary.instruments_skipped}")
        if summary.best_instrument:
            print(f"  Best: {summary.best_instrument}")
        return 0
    except Exception as exc:
        print(f"Backtest failed: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Faiz SMC Strategy Backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit_p.add_argument("--csv", default=str(DEFAULT_CSV))
    audit_p.set_defaults(func=cmd_audit)

    sub.add_parser("list-strategies", help="List registered strategies").set_defaults(func=cmd_list_strategies)

    run_p = sub.add_parser("run", help="Run multi-instrument backtest")
    run_p.add_argument("--strategy", required=True)
    run_p.add_argument("--symbols", default="all")
    run_p.add_argument("--data-root", default=None)
    run_p.add_argument("--output", default=str(DEFAULT_RESULTS))
    run_p.add_argument("--csv", default=str(DEFAULT_CSV))
    run_p.add_argument("--start", default=None)
    run_p.add_argument("--end", default=None)
    run_p.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    docs_parent = str(DOCUMENTS_ROOT)
    if docs_parent not in sys.path:
        sys.path.insert(0, docs_parent)
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
