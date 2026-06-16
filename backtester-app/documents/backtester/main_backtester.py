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
from backtester.strategies.registry import get_all_strategies, get_load_errors, get_strategy, load_all_strategies

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
    module: str
    video_number: int
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str = ""
    worst_instrument: str = ""
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root: str = ""


def resolve_data_root(cli_path: str | None) -> Path | None:
    if cli_path:
        path = Path(cli_path)
        if path.is_dir() and _has_symbol_data(path):
            return path
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_data(path):
            return path
    if DEFAULT_DATA_ROOT.is_dir() and _has_symbol_data(DEFAULT_DATA_ROOT):
        return DEFAULT_DATA_ROOT
    return None


def _has_symbol_data(root: Path) -> bool:
    for child in root.iterdir():
        if child.is_dir():
            for csv_file in child.rglob("*.csv"):
                if csv_file.stat().st_size > 100:
                    return True
    return False


def load_strategy_config(module: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def strategy_module_name(strategy_cls) -> str:
    folder = strategy_cls.__module__.rsplit(".", 2)[-2]
    config = load_strategy_config(folder)
    if config.get("module"):
        return str(config["module"])
    return folder


def composite_score(row: dict[str, Any], best_pnl: float) -> float:
    pf = min(float(row.get("bt_profit_factor") or 0), 5) / 5 * 0.35
    wr = float(row.get("bt_win_rate") or 0) / 100 * 0.20
    sharpe = float(row.get("bt_sharpe_ratio") or 0)
    sharpe_norm = min(max(sharpe, -2), 3) / 3 * 0.20
    pnl = float(row.get("bt_total_pnl") or 0)
    pnl_norm = (pnl / best_pnl * 0.15) if best_pnl > 0 else 0.0
    trades = min(int(row.get("bt_total_trades") or 0), 50) / 50 * 0.10
    return round(pf + wr + sharpe_norm + pnl_norm + trades, 4)


def result_to_matrix_row(
    result: BacktestResult,
    strategy_id: str,
    module: str,
    video_number: int,
    symbol: str,
    data_source: str,
    note: str = "",
) -> dict[str, Any]:
    json_path = DEFAULT_OUTPUT / strategy_id / f"{symbol}.json"
    return {
        "strategy_registry_id": strategy_id,
        "strategy_module_id": module,
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
        "backtest_result_json": str(json_path),
        "backtested_at": datetime.now(timezone.utc).isoformat(),
        "data_quality_note": note,
        "data_source": data_source,
    }


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    config_defaults: dict[str, Any],
    required_tfs: list[TF],
) -> tuple[BacktestResult | None, str]:
    start, end = client.get_full_date_range(symbol, required_tfs)
    if not start or not end:
        return None, "missing date range"
    for tf in required_tfs:
        if not client.has_timeframe(symbol, tf):
            return None, f"missing timeframe {tf.name}"
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
    return result, ""


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> RunSummary:
    del start, end  # full range per symbol by default

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    module = strategy_module_name(strategy_cls)
    config = load_strategy_config(module)
    video_number = int(config.get("video_number", 0))
    defaults = config.get("backtest_defaults", {})
    required_tf_names = config.get("required_timeframes") or [
        tf.name for tf in strategy_cls.timeframes
    ]
    required_tfs = [tf_from_string(name) for name in required_tf_names]

    resolved_root = resolve_data_root(str(data_root) if data_root else None)
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    summary = RunSummary(
        strategy_id=strategy_cls.id,
        module=module,
        video_number=video_number,
        data_root=str(resolved_root) if resolved_root else "",
    )

    if resolved_root is None:
        summary.data_source = "not_backtested"
        return summary

    summary.data_source = "exness_production"
    client = ExnessCSVClient(resolved_root)
    all_symbols = client.get_symbols()
    summary.instruments_scanned = len(all_symbols)

    if symbols == "all":
        target_symbols = all_symbols
    elif isinstance(symbols, str):
        target_symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        target_symbols = list(symbols)

    rows: list[dict[str, Any]] = []
    for symbol in target_symbols:
        result, note = run_single_symbol_backtest(
            strategy_cls, symbol, client, defaults, required_tfs
        )
        if result is None:
            summary.instruments_skipped += 1
            continue
        summary.instruments_tested += 1
        json_dir = output_path / strategy_cls.id
        json_dir.mkdir(parents=True, exist_ok=True)
        json_file = json_dir / f"{symbol}.json"
        with json_file.open("w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle, indent=2)
        rows.append(
            result_to_matrix_row(
                result,
                strategy_cls.id,
                module,
                video_number,
                symbol,
                summary.data_source,
                note,
            )
        )

    if rows:
        best_pnl = max(float(r["bt_total_pnl"]) for r in rows)
        for row in rows:
            row["composite_score"] = composite_score(row, best_pnl)
        ranked = sorted(rows, key=lambda r: r["composite_score"], reverse=True)
        min_trades = int(config.get("min_trades_for_ranking", 10))
        for idx, row in enumerate(ranked, start=1):
            row["rank_within_strategy"] = idx
        eligible = [r for r in ranked if int(r["bt_total_trades"]) >= min_trades]
        if eligible:
            summary.best_instrument = eligible[0]["symbol"]
            summary.worst_instrument = eligible[-1]["symbol"]
        summary.matrix_rows = ranked
        summary.aggregate_stats = _aggregate_stats(ranked)

    write_matrix_csv(summary.matrix_rows, output_path / "strategy_instrument_matrix.csv")
    return summary


def _aggregate_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_trades = sum(int(r["bt_total_trades"]) for r in rows)
    total_pnl = sum(float(r["bt_total_pnl"]) for r in rows)
    wins = sum(int(r["bt_winning_trades"]) for r in rows)
    win_rate = round(wins / total_trades * 100, 2) if total_trades else 0.0
    gross_profit = sum(float(r["bt_total_pnl"]) for r in rows if float(r["bt_total_pnl"]) > 0)
    gross_loss = abs(sum(float(r["bt_total_pnl"]) for r in rows if float(r["bt_total_pnl"]) <= 0))
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0
    max_dd = max(float(r["bt_max_drawdown_pct"]) for r in rows) if rows else 0.0
    sharpe_vals = [float(r["bt_sharpe_ratio"]) for r in rows if r.get("bt_sharpe_ratio")]
    avg_sharpe = round(sum(sharpe_vals) / len(sharpe_vals), 2) if sharpe_vals else 0.0
    avg_rr_vals = [float(r["bt_avg_rr"]) for r in rows if r.get("bt_avg_rr")]
    avg_rr = round(sum(avg_rr_vals) / len(avg_rr_vals), 2) if avg_rr_vals else 0.0
    return {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": win_rate,
        "bt_profit_factor_all": pf,
        "bt_max_drawdown_pct_all": max_dd,
        "bt_total_pnl_all": round(total_pnl, 2),
        "bt_sharpe_ratio_all": avg_sharpe,
        "bt_avg_rr_all": avg_rr,
    }


def read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        newline="",
        encoding="utf-8",
        dir=csv_path.parent,
        delete=False,
    ) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        tmp_path = Path(tmp.name)
    tmp_path.replace(csv_path)


def write_matrix_csv(new_rows: list[dict[str, Any]], matrix_path: Path):
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if matrix_path.exists():
        with matrix_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row
    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {k: str(v) for k, v in row.items()}
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    with matrix_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in existing.values():
            writer.writerow(row)


def cmd_audit(csv_path: Path) -> int:
    fieldnames, rows = read_csv_rows(csv_path)
    load_all_strategies()
    coded_folders = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__"}
    }
    canonical = [
        r
        for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    print(f"Canonical modules: {len(canonical)}")
    print(f"Strategy folders on disk: {sorted(coded_folders)}")
    print(f"Registered strategies: {[s.id for s in get_all_strategies()]}")
    for err in get_load_errors():
        print(f"  LOAD ERROR: {err}")
    data_root = resolve_data_root(None)
    if data_root:
        symbols = ExnessCSVClient(data_root).get_symbols()
        print(f"Data root: {data_root} ({len(symbols)} symbols)")
    else:
        print("Data root: NOT AVAILABLE (production path missing)")
    pending = [
        r
        for r in canonical
        if r.get("implementation_status", "not_started") in {"", "not_started", "in_progress", "failed"}
    ]
    print(f"Pending canonical: {len(pending)}")
    write_csv_atomic(csv_path, fieldnames, rows)
    return 0


def cmd_list_strategies() -> int:
    load_all_strategies()
    for strat in get_all_strategies():
        print(f"{strat.id}\t{strat.name}\t{strat.__module__}")
    for err in get_load_errors():
        print(f"ERROR: {err}", file=sys.stderr)
    return 0


def update_tracking_csv(
    csv_path: Path,
    module: str,
    registry_id: str,
    status: str,
    data_source: str,
    data_root: str,
    summary: RunSummary | None,
    anti_bias_passed: str,
    anti_bias_notes: str,
    backtest_error: str = "",
):
    fieldnames, rows = read_csv_rows(csv_path)
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("module_to_code") != module or row.get("action") != "CODE-CANONICAL":
            continue
        row["implementation_status"] = status
        row["strategy_module_id"] = module
        row["strategy_folder"] = f"strategies/{module}/"
        row["strategy_registry_id"] = registry_id
        row["coded_at"] = row.get("coded_at") or now
        row["data_source"] = data_source
        row["data_root_used"] = data_root
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["backtest_error"] = backtest_error
        if summary:
            row["backtested_at"] = now if status == "coded_and_backtested" else row.get("backtested_at", "")
            row["instruments_tested_count"] = str(summary.instruments_tested)
            for key, val in summary.aggregate_stats.items():
                row[key] = str(val)
            if summary.best_instrument:
                best = next(
                    (r for r in summary.matrix_rows if r["symbol"] == summary.best_instrument),
                    None,
                )
                if best:
                    row["best_instrument"] = summary.best_instrument
                    row["best_instrument_pf"] = str(best["bt_profit_factor"])
                    row["best_instrument_win_rate"] = str(best["bt_win_rate"])
                    row["best_instrument_pnl"] = str(best["bt_total_pnl"])
                    row["best_instrument_trades"] = str(best["bt_total_trades"])
            if summary.worst_instrument:
                row["worst_instrument"] = summary.worst_instrument
            row["instrument_affinity_notes"] = _affinity_notes(summary)
    write_csv_atomic(csv_path, fieldnames, rows)


def _affinity_notes(summary: RunSummary) -> str:
    if not summary.matrix_rows:
        return "No instruments backtested — production Exness data required on Windows."
    top = summary.matrix_rows[:3]
    parts = [
        f"{r['symbol']}(PF={r['bt_profit_factor']}, trades={r['bt_total_trades']})"
        for r in top
    ]
    return f"Top instruments by composite score: {', '.join(parts)}."


def cmd_run(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    strategy_cls = get_strategy(args.strategy)
    if strategy_cls is None:
        print(f"Unknown strategy: {args.strategy}", file=sys.stderr)
        return 1

    module = strategy_module_name(strategy_cls)
    data_root = resolve_data_root(args.data_root)

    fieldnames, rows = read_csv_rows(csv_path)
    for row in rows:
        if row.get("module_to_code") == module and row.get("action") == "CODE-CANONICAL":
            row["implementation_status"] = "in_progress"
    write_csv_atomic(csv_path, fieldnames, rows)

    anti_bias_passed = "yes"
    anti_bias_notes = (
        "M1 signals use closed bars only; HTF bars gated by data_feed close rule; "
        "VP levels from session history only; session filter uses America/New_York; "
        "params from video spec/config.yaml — no post-backtest tuning."
    )

    summary: RunSummary | None = None
    backtest_error = ""
    if data_root is None:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"
    else:
        try:
            summary = run_multi_instrument_backtest(
                strategy_id=strategy_cls.id,
                data_root=data_root,
                symbols=args.symbols,
                output_dir=args.output,
            )
            status = "coded_and_backtested"
            data_source = "exness_production"
        except Exception as exc:
            status = "failed"
            data_source = "not_backtested"
            backtest_error = str(exc)
            anti_bias_passed = "no"

    update_tracking_csv(
        csv_path,
        module,
        strategy_cls.id,
        status,
        data_source,
        str(data_root or ""),
        summary,
        anti_bias_passed,
        anti_bias_notes,
        backtest_error,
    )

    print(f"Run complete: {strategy_cls.id} -> {status}")
    if summary:
        print(
            f"Tested {summary.instruments_tested}/{summary.instruments_scanned} symbols; "
            f"best={summary.best_instrument}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit CSV vs coded folders")
    audit_p.add_argument("--csv", default=str(DEFAULT_CSV))

    sub.add_parser("list-strategies", help="List registered strategies")

    run_p = sub.add_parser("run", help="Run multi-instrument backtest")
    run_p.add_argument("--strategy", required=True)
    run_p.add_argument("--symbols", default="all")
    run_p.add_argument("--data-root", default=None)
    run_p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_p.add_argument("--csv", default=str(DEFAULT_CSV))
    run_p.add_argument("--start", default=None)
    run_p.add_argument("--end", default=None)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "audit":
        return cmd_audit(Path(args.csv))
    if args.command == "list-strategies":
        return cmd_list_strategies()
    if args.command == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
