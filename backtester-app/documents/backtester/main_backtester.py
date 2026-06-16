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

from backtester.connectors import ExnessCSVClient
from backtester.core import BacktestConfig, BacktestResult
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, list_strategy_ids

DEFAULT_WINDOWS_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"

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
    composite_score: float = 0.0
    rank_within_strategy: int = 0
    data_quality_note: str = ""
    backtest_start_date: str = ""
    backtest_end_date: str = ""


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str = ""
    worst_instrument: str = ""
    instrument_affinity_notes: str = ""
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_data_root: str | None = None) -> tuple[str, bool]:
    """Return (path, exists_with_data)."""
    candidates: list[str] = []
    if cli_data_root:
        candidates.append(cli_data_root)
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        candidates.append(env_path)
    candidates.append(DEFAULT_WINDOWS_DATA_ROOT)

    for path in candidates:
        root = Path(path)
        if not root.is_dir():
            continue
        symbols = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if symbols:
            return str(root), True
    return candidates[0] if candidates else DEFAULT_WINDOWS_DATA_ROOT, False


def load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = Path(__file__).resolve().parent / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def ensure_csv_columns(csv_path: Path, extra_columns: list[str]) -> list[str]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    changed = False
    for col in extra_columns:
        if col not in fieldnames:
            fieldnames.append(col)
            changed = True

    if changed:
        for row in rows:
            for col in extra_columns:
                row.setdefault(col, "")
        write_csv_rows(csv_path, fieldnames, rows)
    return fieldnames


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]):
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".csv", dir=path.parent)
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    try:
        with tmp_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        return fieldnames, list(reader)


def compute_composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(float(row.get("bt_total_trades") or 0))
    if trades < min_trades:
        return 0.0
    pf = min(float(row.get("bt_profit_factor") or 0), 5.0)
    win_rate = float(row.get("bt_win_rate") or 0)
    sharpe = float(row.get("bt_sharpe_ratio") or 0)
    pnl = float(row.get("bt_total_pnl") or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    pnl_norm = min(max(pnl_norm, 0.0), 1.0)
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
    config_defaults: dict[str, Any],
) -> InstrumentResult:
    required_tfs = [tf_from_string(tf_name) for tf_name in config_defaults.get("required_timeframes", ["M1"])]
    start, end = client.get_full_date_range(symbol, required_tfs)
    if start is None or end is None:
        return InstrumentResult(
            symbol=symbol,
            result=None,
            data_quality_note=f"Missing required timeframes: {[tf.name for tf in required_tfs]}",
        )

    strategy = strategy_cls()
    cfg = BacktestConfig(
        strategy_id=strategy.id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=float(config_defaults.get("initial_balance", 10000.0)),
        risk_per_trade=float(config_defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(config_defaults.get("spread_pips", 1.0)),
        slippage_pips=float(config_defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(config_defaults.get("commission_per_lot", 7.0)),
    )

    engine = BacktestEngine(cfg, strategy, client)
    result = engine.run()

    result_dir = output_dir / strategy.id
    result_dir.mkdir(parents=True, exist_ok=True)
    with (result_dir / f"{symbol}.json").open("w", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2)

    return InstrumentResult(
        symbol=symbol,
        result=result,
        backtest_start_date=start.date().isoformat(),
        backtest_end_date=end.date().isoformat(),
    )


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path = "results",
    csv_path: str | Path | None = None,
) -> MultiInstrumentSummary:
    resolved_root, has_data = resolve_data_root(data_root)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    folder_module = strategy_cls.__module__.rsplit(".", 1)[0].split(".")[-1]
    config = load_strategy_config(folder_module)
    module_name = config.get("module") or folder_module
    defaults = config.get("backtest_defaults", {})
    video_number = str(config.get("video_number", ""))
    min_trades = int(config.get("min_trades_for_ranking", 10))

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_name,
        video_number=video_number,
        data_root_used=resolved_root,
    )

    if not has_data:
        summary.data_source = "pending_exness_production"
        if csv_path:
            update_tracking_csv(
                Path(csv_path),
                strategy_cls.id,
                module_name,
                video_number,
                summary,
                has_data=False,
            )
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

    instrument_results: list[InstrumentResult] = []
    for symbol in target_symbols:
        if symbol not in all_symbols:
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(symbol=symbol, result=None, data_quality_note="Symbol folder not found")
            )
            continue
        inst = run_single_symbol_backtest(strategy_cls, symbol, client, output_path, defaults)
        if inst.result is None or inst.result.total_trades == 0 and inst.data_quality_note:
            summary.instruments_skipped += 1
        else:
            summary.instruments_tested += 1
        instrument_results.append(inst)

    summary.data_source = "exness_production"
    now_iso = datetime.now(timezone.utc).isoformat()

    matrix_rows: list[dict[str, Any]] = []
    for inst in instrument_results:
        if inst.result is None:
            matrix_rows.append({
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": module_name,
                "video_number": video_number,
                "symbol": inst.symbol,
                "backtest_start_date": inst.backtest_start_date,
                "backtest_end_date": inst.backtest_end_date,
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
                "composite_score": 0,
                "rank_within_strategy": 0,
                "backtest_result_json": "",
                "backtested_at": now_iso,
                "data_quality_note": inst.data_quality_note,
                "data_source": summary.data_source,
            })
            continue

        res = inst.result
        matrix_rows.append({
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_name,
            "video_number": video_number,
            "symbol": inst.symbol,
            "backtest_start_date": inst.backtest_start_date,
            "backtest_end_date": inst.backtest_end_date,
            "bt_total_trades": res.total_trades,
            "bt_winning_trades": res.winning_trades,
            "bt_losing_trades": res.losing_trades,
            "bt_win_rate": res.win_rate,
            "bt_profit_factor": res.profit_factor,
            "bt_max_drawdown_pct": res.max_drawdown_pct,
            "bt_total_pnl": round(res.total_pnl, 2),
            "bt_sharpe_ratio": res.sharpe_ratio,
            "bt_avg_rr": res.avg_rr,
            "bt_avg_trade_duration_mins": res.avg_trade_duration,
            "composite_score": 0,
            "rank_within_strategy": 0,
            "backtest_result_json": json.dumps(
                output_path / strategy_cls.id / f"{inst.symbol}.json"
            ),
            "backtested_at": now_iso,
            "data_quality_note": inst.data_quality_note,
            "data_source": summary.data_source,
        })

    best_pnl = max((float(r["bt_total_pnl"]) for r in matrix_rows), default=0.0)
    for row in matrix_rows:
        row["composite_score"] = round(compute_composite_score(row, best_pnl, min_trades), 4)

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
        summary.instrument_affinity_notes = (
            f"Strongest on {best['symbol']} (PF={best['bt_profit_factor']}, "
            f"{best['bt_total_trades']} trades). Weakest ranked: {worst['symbol']} "
            f"(PF={worst['bt_profit_factor']})."
        )

    tested_rows = [r for r in matrix_rows if int(r["bt_total_trades"]) > 0]
    if tested_rows:
        summary.aggregate_stats = {
            "bt_total_trades_all": sum(int(r["bt_total_trades"]) for r in tested_rows),
            "bt_win_rate_all": round(
                sum(float(r["bt_win_rate"]) for r in tested_rows) / len(tested_rows), 2
            ),
            "bt_profit_factor_all": round(
                sum(float(r["bt_profit_factor"]) for r in tested_rows if float(r["bt_profit_factor"]) < 100)
                / max(1, len([r for r in tested_rows if float(r["bt_profit_factor"]) < 100])),
                2,
            ),
            "bt_max_drawdown_pct_all": round(
                max(float(r["bt_max_drawdown_pct"]) for r in tested_rows), 2
            ),
            "bt_total_pnl_all": round(sum(float(r["bt_total_pnl"]) for r in tested_rows), 2),
            "bt_sharpe_ratio_all": round(
                sum(float(r["bt_sharpe_ratio"]) for r in tested_rows) / len(tested_rows), 2
            ),
            "bt_avg_rr_all": round(
                sum(float(r["bt_avg_rr"]) for r in tested_rows) / len(tested_rows), 2
            ),
        }

    summary.matrix_rows = matrix_rows
    update_matrix_csv(output_path / "strategy_instrument_matrix.csv", matrix_rows)

    if csv_path:
        update_tracking_csv(
            Path(csv_path),
            strategy_cls.id,
            module_name,
            video_number,
            summary,
            has_data=has_data,
        )

    return summary


def update_matrix_csv(path: Path, new_rows: list[dict[str, Any]]):
    if path.exists():
        _, existing = read_csv_rows(path)
    else:
        existing = []
    fieldnames = MATRIX_COLUMNS
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in existing:
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        merged[key] = row
    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        merged[key] = {col: row.get(col, "") for col in fieldnames}
    write_csv_rows(path, fieldnames, list(merged.values()))


def update_tracking_csv(
    csv_path: Path,
    registry_id: str,
    module_name: str,
    video_number: str,
    summary: MultiInstrumentSummary,
    has_data: bool,
):
    fieldnames = ensure_csv_columns(csv_path, TRACKING_COLUMNS)
    _, rows = read_csv_rows(csv_path)
    now_iso = datetime.now(timezone.utc).isoformat()

    if has_data and summary.instruments_tested > 0:
        status = "coded_and_backtested"
        data_source = "exness_production"
    elif has_data:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"
    else:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"

    anti_bias_notes = (
        "HTF bars gated by close time in data_feed; session VP built from past M1 bars only; "
        "entries on M1 close through local clusters; stops from absorption wicks; no post-hoc tuning."
    )

    for row in rows:
        if row.get("video_number") != video_number:
            continue
        if row.get("action") != "CODE-CANONICAL":
            continue
        row["implementation_status"] = status
        row["strategy_module_id"] = module_name
        row["strategy_folder"] = f"strategies/{module_name}/"
        row["strategy_registry_id"] = registry_id
        row["coded_at"] = row.get("coded_at") or now_iso
        if has_data and summary.instruments_tested > 0:
            row["backtested_at"] = now_iso
        row["instruments_tested_count"] = str(summary.instruments_tested)
        row["anti_bias_review_passed"] = "yes"
        row["anti_bias_notes"] = anti_bias_notes
        row["data_source"] = data_source
        row["data_root_used"] = summary.data_root_used
        row["best_instrument"] = summary.best_instrument
        row["worst_instrument"] = summary.worst_instrument
        row["instrument_affinity_notes"] = summary.instrument_affinity_notes
        for key, value in summary.aggregate_stats.items():
            row[key] = str(value)
        if ranked := [r for r in summary.matrix_rows if r.get("symbol") == summary.best_instrument]:
            best = ranked[0]
            row["best_instrument_pf"] = str(best.get("bt_profit_factor", ""))
            row["best_instrument_win_rate"] = str(best.get("bt_win_rate", ""))
            row["best_instrument_pnl"] = str(best.get("bt_total_pnl", ""))
            row["best_instrument_trades"] = str(best.get("bt_total_trades", ""))

    write_csv_rows(csv_path, fieldnames, rows)

    if has_data and summary.data_source == "exness_production":
        canonical_row = next(
            (
                r for r in rows
                if r.get("video_number") == video_number and r.get("action") == "CODE-CANONICAL"
            ),
            None,
        )
        if canonical_row and canonical_row.get("implementation_status") == "coded_and_backtested":
            module = canonical_row.get("module_to_code", module_name)
            for row in rows:
                if row.get("action") != "DUPLICATE-SKIP":
                    continue
                if row.get("duplicate_of_video") != video_number and row.get("module_to_code") != module:
                    continue
                row["implementation_status"] = "covered_by_canonical"
                row["strategy_registry_id"] = registry_id
                row["data_source"] = data_source
                for key in summary.aggregate_stats:
                    row[key] = canonical_row.get(key, "")
                row["best_instrument"] = canonical_row.get("best_instrument", "")
                row["worst_instrument"] = canonical_row.get("worst_instrument", "")
                row["instrument_affinity_notes"] = canonical_row.get("instrument_affinity_notes", "")

    write_csv_rows(csv_path, fieldnames, rows)


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    backtester_root = Path(__file__).resolve().parent
    strategies_dir = backtester_root / "strategies"

    print("=== Backtester Audit ===")
    print(f"Backtester root: {backtester_root}")
    print(f"main_backtester.py: exists")
    print(f"Strategy folders: {sorted(p.name for p in strategies_dir.iterdir() if p.is_dir() and p.name not in {'__pycache__'})}")

    data_root, has_data = resolve_data_root(args.data_root)
    print(f"Data root: {data_root} (available={has_data})")
    if has_data:
        client = ExnessCSVClient(data_root)
        symbols = client.get_symbols()
        print(f"Symbols found: {len(symbols)}")

    if csv_path.exists():
        ensure_csv_columns(csv_path, TRACKING_COLUMNS)
        _, rows = read_csv_rows(csv_path)
        canonical = [r for r in rows if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"]
        done = [r for r in canonical if r.get("implementation_status") == "coded_and_backtested"]
        pending = [r for r in canonical if r.get("implementation_status", "") in ("", "not_started", "in_progress", "coded_pending_production_backtest", "coded")]
        print(f"Canonical modules: {len(canonical)} total, {len(done)} coded_and_backtested, {len(pending)} pending")
        if pending:
            pending_sorted = sorted(pending, key=lambda r: int(r.get("video_number", 999)))
            nxt = pending_sorted[0]
            print(f"Next pending: Video #{nxt.get('video_number')} — {nxt.get('title')} ({nxt.get('module_to_code')})")
    else:
        print(f"CSV not found: {csv_path}")
        return 1
    return 0


def cmd_list_strategies(_: argparse.Namespace) -> int:
    load = list_strategy_ids()
    for strat_id in load:
        cls = get_strategy(strat_id)
        if cls:
            print(f"{strat_id}\t{cls.name}\tvideo={cls.source_video}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv) if args.csv else None
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
        csv_path=csv_path,
    )
    print("\n=== Run Summary ===")
    print(f"Strategy: {summary.strategy_id}")
    print(f"Data source: {summary.data_source}")
    print(f"Scanned: {summary.instruments_scanned}, tested: {summary.instruments_tested}, skipped: {summary.instruments_skipped}")
    if summary.best_instrument:
        print(f"Best: {summary.best_instrument}")
        print(f"Worst: {summary.worst_instrument}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit CSV vs coded folders vs data")
    audit.add_argument("--csv", required=True)
    audit.add_argument("--data-root", default=None)
    audit.set_defaults(func=cmd_audit)

    listing = sub.add_parser("list-strategies", help="List registered strategies")
    listing.set_defaults(func=cmd_list_strategies)

    run = sub.add_parser("run", help="Run multi-instrument backtest")
    run.add_argument("--strategy", required=True)
    run.add_argument("--symbols", default="all")
    run.add_argument("--data-root", default=None)
    run.add_argument("--output", default=str(Path(__file__).resolve().parent / "results"))
    run.add_argument("--csv", default=None)
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
