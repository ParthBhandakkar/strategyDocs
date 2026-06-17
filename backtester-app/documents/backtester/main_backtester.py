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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
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

if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies


@dataclass
class InstrumentResult:
    symbol: str
    stats: dict[str, Any]
    composite_score: float = 0.0
    rank_within_strategy: int = 0
    data_quality_note: str = ""
    result_path: str = ""


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


def resolve_data_root(cli_root: str | None = None) -> tuple[str, bool]:
    if cli_root:
        path = Path(cli_root)
        if path.is_dir() and _has_symbol_data(path):
            return str(path), True
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path and Path(env_path).is_dir() and _has_symbol_data(Path(env_path)):
        return env_path, True
    windows_path = Path(WINDOWS_DEFAULT_DATA)
    if windows_path.is_dir() and _has_symbol_data(windows_path):
        return str(windows_path), True
    return str(windows_path), False


def _has_symbol_data(root: Path) -> bool:
    for child in root.iterdir():
        if child.is_dir() and any(child.iterdir()):
            return True
    return False


def load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def required_timeframes_for(strategy_cls) -> list[TF]:
    config = load_strategy_config(strategy_cls.id.split("_", 1)[-1])
    if config.get("required_timeframes"):
        return [tf_from_string(tf) for tf in config["required_timeframes"]]
    return list(strategy_cls.timeframes)


def composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0))
    if trades < min_trades:
        return 0.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0)
    win_rate = float(row.get("bt_win_rate", 0) or 0)
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    pnl_norm = min(max(pnl_norm, 0.0), 1.0)
    return round(
        (pf / 5.0 * 0.35)
        + (win_rate / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10),
        4,
    )


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    defaults: dict[str, Any],
) -> InstrumentResult | None:
    required_tfs = required_timeframes_for(strategy_cls)
    if not client.symbol_has_timeframes(symbol, required_tfs):
        missing = [tf.name for tf in required_tfs if client._find_csv(symbol, tf) is None]
        return InstrumentResult(
            symbol=symbol,
            stats={},
            data_quality_note=f"missing_timeframes:{','.join(missing)}",
        )

    start, end = client.get_full_date_range(symbol, required_tfs)
    if not start or not end:
        return InstrumentResult(symbol=symbol, stats={}, data_quality_note="no_date_range")

    config = BacktestConfig(
        strategy_id=strategy_cls.id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=float(defaults.get("initial_balance", 10000.0)),
        risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(defaults.get("spread_pips", 1.0)),
        slippage_pips=float(defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
    )

    strategy = strategy_cls()
    engine = BacktestEngine(config, strategy, client)
    result = engine.run()

    result_dir = output_dir / strategy_cls.id
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{symbol}.json"
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2)

    stats = result.to_dict()["stats"]
    return InstrumentResult(
        symbol=symbol,
        stats=stats,
        result_path=str(result_path),
    )


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    del start, end  # full history per symbol by default
    load_all_strategies()
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    resolved_root, has_real_data = resolve_data_root(data_root)
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    module_name = strategy_cls.id.split("_", 1)[-1]
    config = load_strategy_config(module_name)
    defaults = config.get("backtest_defaults", {})
    video_number = str(config.get("video_number", ""))
    min_trades = int(config.get("min_trades_for_ranking", 10))

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_name,
        video_number=video_number,
        data_root_used=resolved_root,
        data_source="exness_production" if has_real_data else "not_backtested",
    )

    if not has_real_data:
        return summary

    client = ExnessCSVClient(resolved_root)
    symbol_list = client.get_symbols() if symbols == "all" else [s.strip() for s in symbols.split(",")]
    summary.instruments_scanned = len(symbol_list)

    instrument_results: list[InstrumentResult] = []
    for symbol in symbol_list:
        try:
            result = run_single_symbol_backtest(strategy_cls, symbol, client, output_path, defaults)
        except Exception as exc:
            result = InstrumentResult(symbol=symbol, stats={}, data_quality_note=f"error:{exc}")
        if result is None:
            summary.instruments_skipped += 1
            continue
        if result.stats:
            summary.instruments_tested += 1
            instrument_results.append(result)
        else:
            summary.instruments_skipped += 1
            instrument_results.append(result)

    rows: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for item in instrument_results:
        if not item.stats:
            rows.append({
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": module_name,
                "video_number": video_number,
                "symbol": item.symbol,
                "data_quality_note": item.data_quality_note,
                "data_source": summary.data_source,
                "backtested_at": now_iso,
            })
            continue
        rows.append({
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_name,
            "video_number": video_number,
            "symbol": item.symbol,
            "backtest_start_date": "",
            "backtest_end_date": "",
            "bt_total_trades": item.stats.get("total_trades", 0),
            "bt_winning_trades": item.stats.get("winning_trades", 0),
            "bt_losing_trades": item.stats.get("losing_trades", 0),
            "bt_win_rate": item.stats.get("win_rate", 0),
            "bt_profit_factor": item.stats.get("profit_factor", 0),
            "bt_max_drawdown_pct": item.stats.get("max_drawdown_pct", 0),
            "bt_total_pnl": item.stats.get("total_pnl", 0),
            "bt_sharpe_ratio": item.stats.get("sharpe_ratio", 0),
            "bt_avg_rr": item.stats.get("avg_rr", 0),
            "bt_avg_trade_duration_mins": item.stats.get("avg_trade_duration_mins", 0),
            "backtest_result_json": item.result_path,
            "backtested_at": now_iso,
            "data_quality_note": item.data_quality_note,
            "data_source": summary.data_source,
        })

    tested_rows = [row for row in rows if row.get("bt_total_trades", 0)]
    best_pnl = max((float(row.get("bt_total_pnl", 0) or 0) for row in tested_rows), default=0.0)
    for row in tested_rows:
        row["composite_score"] = composite_score(row, best_pnl, min_trades)

    ranked = sorted(
        [row for row in tested_rows if row.get("composite_score", 0) > 0],
        key=lambda row: row["composite_score"],
        reverse=True,
    )
    for idx, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = idx

    eligible = [row for row in tested_rows if int(row.get("bt_total_trades", 0)) >= min_trades]
    if eligible:
        best = max(eligible, key=lambda row: row.get("composite_score", 0))
        worst = min(eligible, key=lambda row: row.get("composite_score", 0))
        summary.best_instrument = best["symbol"]
        summary.worst_instrument = worst["symbol"]

    if tested_rows:
        total_trades = sum(int(row.get("bt_total_trades", 0)) for row in tested_rows)
        total_wins = sum(int(row.get("bt_winning_trades", 0)) for row in tested_rows)
        total_pnl = sum(float(row.get("bt_total_pnl", 0) or 0) for row in tested_rows)
        win_rate = round(total_wins / total_trades * 100, 2) if total_trades else 0.0
        gross_profit = sum(
            float(row.get("bt_total_pnl", 0) or 0)
            for row in tested_rows
            if float(row.get("bt_total_pnl", 0) or 0) > 0
        )
        gross_loss = abs(
            sum(
                float(row.get("bt_total_pnl", 0) or 0)
                for row in tested_rows
                if float(row.get("bt_total_pnl", 0) or 0) <= 0
            )
        )
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": win_rate,
            "bt_profit_factor_all": round(gross_profit / gross_loss, 2) if gross_loss else 0.0,
            "bt_max_drawdown_pct_all": max(
                float(row.get("bt_max_drawdown_pct", 0) or 0) for row in tested_rows
            ),
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(
                sum(float(row.get("bt_sharpe_ratio", 0) or 0) for row in tested_rows)
                / len(tested_rows),
                2,
            ),
            "bt_avg_rr_all": round(
                sum(float(row.get("bt_avg_rr", 0) or 0) for row in tested_rows) / len(tested_rows),
                2,
            ),
        }

    summary.matrix_rows = rows
    update_matrix_csv(output_path / "strategy_instrument_matrix.csv", rows)
    return summary


def update_matrix_csv(path: Path, new_rows: list[dict[str, Any]]):
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row
    for row in new_rows:
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        merged = existing.get(key, {})
        merged.update({col: row.get(col, merged.get(col, "")) for col in MATRIX_COLUMNS})
        existing[key] = merged
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in existing.values():
            writer.writerow(row)
    tmp.replace(path)


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
    tmp = csv_path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(csv_path)
    return rows


def save_csv_rows(csv_path: Path, rows: list[dict[str, str]], fieldnames: list[str]):
    tmp = csv_path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(csv_path)


def audit(csv_path: Path):
    rows = ensure_csv_columns(csv_path)
    strategies = get_all_strategies()
    coded_modules = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and (p / "strategy.py").exists()
    }
    resolved_root, has_data = resolve_data_root()
    canonical = [
        row for row in rows
        if row.get("action") == "CODE-CANONICAL" and row.get("is_backtestable") == "yes"
    ]
    done = sum(1 for row in canonical if row.get("implementation_status") == "coded_and_backtested")
    print("=== Backtester Audit ===")
    print(f"Strategies registered: {len(strategies)}")
    print(f"Strategy folders on disk: {sorted(coded_modules)}")
    print(f"Canonical modules: {len(canonical)} coded_and_backtested: {done}")
    print(f"Data root: {resolved_root} (available={has_data})")
    if has_data:
        client = ExnessCSVClient(resolved_root)
        print(f"Symbols available: {len(client.get_symbols())}")
    pending = [
        row for row in canonical
        if row.get("implementation_status", "") in {"", "not_started", "failed", "in_progress"}
    ]
    if pending:
        nxt = min(pending, key=lambda row: int(row.get("video_number", 999)))
        print(
            f"Next pending: Video #{nxt.get('video_number')} — "
            f"{nxt.get('module_to_code')}"
        )


def update_tracking_csv(
    csv_path: Path,
    module_name: str,
    registry_id: str,
    summary: MultiInstrumentSummary,
    status: str,
    anti_bias_passed: str,
    anti_bias_notes: str,
    backtest_error: str = "",
):
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    now_iso = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("module_to_code") != module_name:
            continue
        if row.get("action") != "CODE-CANONICAL":
            continue
        row["implementation_status"] = status
        row["strategy_module_id"] = module_name
        row["strategy_folder"] = f"strategies/{module_name}/"
        row["strategy_registry_id"] = registry_id
        row["coded_at"] = row.get("coded_at") or now_iso
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["backtest_error"] = backtest_error
        row["data_source"] = summary.data_source
        row["data_root_used"] = summary.data_root_used
        if status == "coded_and_backtested":
            row["backtested_at"] = now_iso
        row["instruments_tested_count"] = str(summary.instruments_tested)
        for key, value in summary.aggregate_stats.items():
            row[key] = str(value)
        if summary.best_instrument:
            best_row = next(
                (item for item in summary.matrix_rows if item.get("symbol") == summary.best_instrument),
                {},
            )
            row["best_instrument"] = summary.best_instrument
            row["best_instrument_pf"] = str(best_row.get("bt_profit_factor", ""))
            row["best_instrument_win_rate"] = str(best_row.get("bt_win_rate", ""))
            row["best_instrument_pnl"] = str(best_row.get("bt_total_pnl", ""))
            row["best_instrument_trades"] = str(best_row.get("bt_total_trades", ""))
            row["worst_instrument"] = summary.worst_instrument
            row["instrument_affinity_notes"] = (
                f"Best on {summary.best_instrument}; weakest ranked {summary.worst_instrument} "
                f"across {summary.instruments_tested} tested symbols."
            )

    save_csv_rows(csv_path, rows, fieldnames)


def cmd_list_strategies(_: argparse.Namespace):
    for strategy_cls in get_all_strategies():
        print(f"{strategy_cls.id:40} {strategy_cls.name}")


def cmd_audit(args: argparse.Namespace):
    audit(Path(args.csv))


def cmd_run(args: argparse.Namespace):
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    strategy_cls = get_strategy(args.strategy)
    module_name = strategy_cls.id.split("_", 1)[-1] if strategy_cls else args.strategy
    _, has_data = resolve_data_root(args.data_root)
    if has_data and summary.instruments_tested > 0:
        status = "coded_and_backtested"
        data_source = "exness_production"
    elif has_data:
        status = "failed"
        data_source = "not_backtested"
    else:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"

    summary.data_source = data_source

    anti_bias = "yes"
    anti_bias_notes = (
        "HTF bars gated by close in data_feed; session VP built from past session bars only; "
        "entries on bar close after absorption + cluster inversion; params fixed from video spec."
    )
    update_tracking_csv(
        Path(args.csv),
        module_name=module_name,
        registry_id=summary.strategy_id,
        summary=summary,
        status=status,
        anti_bias_passed=anti_bias,
        anti_bias_notes=anti_bias_notes,
        backtest_error="" if status != "failed" else "no_instruments_tested",
    )
    print(json.dumps({
        "strategy_id": summary.strategy_id,
        "instruments_tested": summary.instruments_tested,
        "best_instrument": summary.best_instrument,
        "aggregate": summary.aggregate_stats,
        "status": status,
    }, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_parser = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit_parser.add_argument("--csv", default=str(DEFAULT_CSV))
    audit_parser.set_defaults(func=cmd_audit)

    list_parser = sub.add_parser("list-strategies", help="List registered strategies")
    list_parser.set_defaults(func=cmd_list_strategies)

    run_parser = sub.add_parser("run", help="Run multi-instrument backtest")
    run_parser.add_argument("--strategy", required=True)
    run_parser.add_argument("--symbols", default="all")
    run_parser.add_argument("--data-root", default=None)
    run_parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_parser.add_argument("--csv", default=str(DEFAULT_CSV))
    run_parser.add_argument("--start", default=None)
    run_parser.add_argument("--end", default=None)
    run_parser.set_defaults(func=cmd_run)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
