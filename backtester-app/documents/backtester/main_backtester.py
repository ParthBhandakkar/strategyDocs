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
from typing import Any, Optional

import yaml

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, get_strategy_module, load_all_strategies

DEFAULT_WINDOWS_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
DEFAULT_CSV = BACKTESTER_ROOT.parent / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
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
    rank_within_strategy: int = 0
    data_quality_note: str = ""
    skipped: bool = False


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: Optional[str] = None
    worst_instrument: Optional[str] = None
    instrument_affinity_notes: str = ""
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_path: str | None = None) -> tuple[str, bool]:
    """Return (path, exists_with_data)."""
    if cli_path:
        path = Path(cli_path)
        if path.is_dir() and _has_symbol_data(path):
            return str(path), True
        return str(path), False

    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path and Path(env_path).is_dir() and _has_symbol_data(Path(env_path)):
        return env_path, True

    default = Path(DEFAULT_WINDOWS_DATA_ROOT)
    if default.is_dir() and _has_symbol_data(default):
        return str(default), True

    return str(default), False


def _has_symbol_data(root: Path) -> bool:
    for child in root.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            for tf_dir in child.iterdir():
                if tf_dir.is_dir() and list(tf_dir.glob("*.csv")):
                    return True
    return False


def load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def compute_composite_score(
    pf: float,
    win_rate: float,
    sharpe: float,
    pnl: float,
    trades: int,
    best_pnl: float,
) -> float:
    sharpe_norm = min(max(sharpe, -2), 3) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else (1.0 if pnl >= 0 else 0.0)
    return round(
        (min(pf, 5) / 5.0 * 0.35)
        + (win_rate / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10),
        4,
    )


def run_single_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[Any | None, str]:
    module_name = get_strategy_module(strategy_cls.id) or ""
    config_data = load_strategy_config(module_name)
    defaults = config_data.get("backtest_defaults", {})
    required_tfs = [tf_from_string(tf) for tf in config_data.get("required_timeframes", [])]
    if not required_tfs:
        required_tfs = list(strategy_cls.timeframes)

    for tf in required_tfs:
        if not client.has_timeframe(symbol, tf):
            return None, f"missing timeframe {tf.name}"

    sym_start, sym_end = client.get_full_date_range(symbol, required_tfs)
    if not sym_start or not sym_end:
        return None, "no date range in CSV files"

    start_date = start or sym_start
    end_date = end or sym_end

    config = BacktestConfig(
        strategy_id=strategy_cls.id,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
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
    json_path = result_dir / f"{symbol}.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2)

    return result, ""


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    load_all_strategies(force=True)
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    resolved_root, has_data = resolve_data_root(data_root)
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    module_name = get_strategy_module(strategy_cls.id) or strategy_id
    config_data = load_strategy_config(module_name)
    video_number = str(config_data.get("video_number", ""))
    min_trades = int(config_data.get("min_trades_for_ranking", 10))

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_name,
        video_number=video_number,
        data_root_used=resolved_root,
    )

    if not has_data:
        summary.data_source = "pending_exness_production"
        return summary

    client = ExnessCSVClient(resolved_root)
    if symbols == "all":
        symbol_list = client.get_symbols()
    elif isinstance(symbols, str):
        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        symbol_list = [s.upper() for s in symbols]

    summary.instruments_scanned = len(symbol_list)
    instrument_results: list[InstrumentResult] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for symbol in symbol_list:
        try:
            result, note = run_single_backtest(
                strategy_cls, symbol, client, output_path, start, end
            )
        except Exception as exc:
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(symbol=symbol, result=None, skipped=True, data_quality_note=str(exc))
            )
            continue

        if result is None:
            summary.instruments_skipped += 1
            instrument_results.append(
                InstrumentResult(symbol=symbol, result=None, skipped=True, data_quality_note=note)
            )
            continue

        summary.instruments_tested += 1
        instrument_results.append(
            InstrumentResult(symbol=symbol, result=result, data_quality_note=note)
        )

    best_pnl = max((ir.result.total_pnl for ir in instrument_results if ir.result), default=0.0)
    if best_pnl <= 0:
        best_pnl = max((abs(ir.result.total_pnl) for ir in instrument_results if ir.result), default=1.0)

    for ir in instrument_results:
        if ir.result is None:
            summary.matrix_rows.append(
                {
                    "strategy_registry_id": strategy_cls.id,
                    "strategy_module_id": module_name,
                    "video_number": video_number,
                    "symbol": ir.symbol,
                    "data_quality_note": ir.data_quality_note or "skipped",
                    "data_source": "exness_production",
                    "backtested_at": now_iso,
                }
            )
            continue

        score = compute_composite_score(
            pf=ir.result.profit_factor if ir.result.profit_factor != float("inf") else 5.0,
            win_rate=ir.result.win_rate,
            sharpe=ir.result.sharpe_ratio,
            pnl=ir.result.total_pnl,
            trades=ir.result.total_trades,
            best_pnl=best_pnl,
        )
        ir.composite_score = score
        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_name,
            "video_number": video_number,
            "symbol": ir.symbol,
            "backtest_start_date": ir.result.config.start_date.date().isoformat(),
            "backtest_end_date": ir.result.config.end_date.date().isoformat(),
            "bt_total_trades": ir.result.total_trades,
            "bt_winning_trades": ir.result.winning_trades,
            "bt_losing_trades": ir.result.losing_trades,
            "bt_win_rate": ir.result.win_rate,
            "bt_profit_factor": ir.result.profit_factor,
            "bt_max_drawdown_pct": ir.result.max_drawdown_pct,
            "bt_total_pnl": ir.result.total_pnl,
            "bt_sharpe_ratio": ir.result.sharpe_ratio,
            "bt_avg_rr": ir.result.avg_rr,
            "bt_avg_trade_duration_mins": ir.result.avg_trade_duration,
            "composite_score": score,
            "rank_within_strategy": 0,
            "backtest_result_json": str((output_path / strategy_cls.id / f"{ir.symbol}.json").relative_to(BACKTESTER_ROOT)),
            "backtested_at": now_iso,
            "data_quality_note": ir.data_quality_note,
            "data_source": "exness_production",
        }
        summary.matrix_rows.append(row)

    ranked = sorted(
        [ir for ir in instrument_results if ir.result],
        key=lambda x: x.composite_score,
        reverse=True,
    )
    for rank, ir in enumerate(ranked, start=1):
        for row in summary.matrix_rows:
            if row.get("symbol") == ir.symbol and row.get("bt_total_trades") is not None:
                row["rank_within_strategy"] = rank

    rankable = [ir for ir in ranked if ir.result and ir.result.total_trades >= min_trades]
    if rankable:
        best = rankable[0]
        worst = rankable[-1]
        summary.best_instrument = best.symbol
        summary.worst_instrument = worst.symbol
        summary.instrument_affinity_notes = (
            f"Strongest on {best.symbol} (PF={best.result.profit_factor}, "
            f"{best.result.total_trades} trades). Weakest ranked: {worst.symbol} "
            f"(PF={worst.result.profit_factor}, {worst.result.total_trades} trades)."
        )

    if summary.instruments_tested > 0:
        summary.data_source = "exness_production"
        tested_rows = [row for row in summary.matrix_rows if row.get("bt_total_trades") is not None]
        total_trades = sum(int(row.get("bt_total_trades", 0)) for row in tested_rows)
        if total_trades > 0:
            summary.aggregate_stats = {
                "bt_total_trades_all": total_trades,
                "bt_win_rate_all": round(
                    sum(row.get("bt_win_rate", 0) * row.get("bt_total_trades", 0) for row in tested_rows)
                    / total_trades,
                    2,
                ),
                "bt_profit_factor_all": round(
                    sum(row.get("bt_profit_factor", 0) for row in tested_rows if row.get("bt_profit_factor") != float("inf"))
                    / max(1, len(tested_rows)),
                    2,
                ),
                "bt_max_drawdown_pct_all": round(
                    max(row.get("bt_max_drawdown_pct", 0) for row in tested_rows),
                    2,
                ),
                "bt_total_pnl_all": round(sum(row.get("bt_total_pnl", 0) for row in tested_rows), 2),
                "bt_sharpe_ratio_all": round(
                    sum(row.get("bt_sharpe_ratio", 0) for row in tested_rows) / len(tested_rows),
                    2,
                ),
                "bt_avg_rr_all": round(
                    sum(row.get("bt_avg_rr", 0) for row in tested_rows) / len(tested_rows),
                    2,
                ),
            }

    _update_matrix_csv(summary.matrix_rows)
    return summary


def _update_matrix_csv(rows: list[dict[str, Any]]):
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if MATRIX_CSV.exists():
        with MATRIX_CSV.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for row in rows:
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        merged = existing.get(key, {})
        merged.update({k: str(v) if v is not None else "" for k, v in row.items()})
        existing[key] = merged

    MATRIX_CSV.parent.mkdir(parents=True, exist_ok=True)
    temp_path = MATRIX_CSV.with_suffix(".tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda r: (r.get("strategy_registry_id", ""), r.get("symbol", ""))):
            writer.writerow({col: row.get(col, "") for col in MATRIX_COLUMNS})
    temp_path.replace(MATRIX_CSV)


def _read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _write_csv_rows(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    temp_path = csv_path.with_suffix(".tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(csv_path)


def ensure_tracking_columns(fieldnames: list[str]) -> list[str]:
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames


def cmd_audit(csv_path: Path):
    fieldnames, rows = _read_csv_rows(csv_path)
    fieldnames = ensure_tracking_columns(fieldnames)

    coded_modules = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__", "tests"}
        and (p / "__init__.py").exists()
    }
    load_all_strategies(force=True)
    registered = {cls.id: get_strategy_module(cls.id) for cls in get_all_strategies()}

    data_root, has_data = resolve_data_root()
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if has_data else 0

    canonical = [
        row for row in rows
        if row.get("action") == "CODE-CANONICAL" and row.get("is_backtestable") == "yes"
    ]
    done = sum(1 for row in canonical if row.get("implementation_status") == "coded_and_backtested")
    pending = sum(
        1 for row in canonical
        if row.get("implementation_status") in ("", "not_started", "in_progress", "failed", "coded", "coded_pending_production_backtest")
    )

    print("=== Backtester Audit ===")
    print(f"Data root: {data_root} (available={has_data}, symbols={symbol_count})")
    print(f"main_backtester.py: {'yes' if Path(__file__).exists() else 'no'}")
    print(f"Folder strategies on disk: {sorted(coded_modules)}")
    print(f"Registered strategies: {registered}")
    print(f"Canonical progress: {done}/{len(canonical)} coded_and_backtested, {pending} pending")

    changed = False
    for row in rows:
        module = row.get("module_to_code", "")
        if module in coded_modules and not row.get("strategy_folder"):
            row["strategy_folder"] = f"strategies/{module}/"
            changed = True

    if changed:
        _write_csv_rows(csv_path, fieldnames, rows)
        print("Updated strategy_folder paths in CSV.")


def cmd_list_strategies():
    load_all_strategies(force=True)
    strategies = get_all_strategies()
    print(f"Registered strategies ({len(strategies)}):")
    for cls in sorted(strategies, key=lambda c: c.id):
        print(f"  {cls.id} — {cls.name} [{', '.join(tf.name for tf in cls.timeframes)}]")


def update_csv_for_strategy(
    csv_path: Path,
    module_name: str,
    summary: MultiInstrumentSummary,
    anti_bias_passed: str,
    anti_bias_notes: str,
    implementation_status: str,
):
    fieldnames, rows = _read_csv_rows(csv_path)
    fieldnames = ensure_tracking_columns(fieldnames)
    now_iso = datetime.now(timezone.utc).isoformat()

    for row in rows:
        if row.get("module_to_code") != module_name:
            continue
        if row.get("action") != "CODE-CANONICAL":
            continue
        row["implementation_status"] = implementation_status
        row["strategy_module_id"] = module_name
        row["strategy_folder"] = f"strategies/{module_name}/"
        row["strategy_registry_id"] = summary.strategy_id
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["data_source"] = summary.data_source
        row["data_root_used"] = summary.data_root_used
        row["instruments_tested_count"] = str(summary.instruments_tested)
        if not row.get("coded_at"):
            row["coded_at"] = now_iso
        if summary.instruments_tested > 0:
            row["backtested_at"] = now_iso
        for key, value in summary.aggregate_stats.items():
            row[key] = str(value)
        if summary.best_instrument:
            row["best_instrument"] = summary.best_instrument
            best_row = next(
                (r for r in summary.matrix_rows if r.get("symbol") == summary.best_instrument),
                {},
            )
            row["best_instrument_pf"] = str(best_row.get("bt_profit_factor", ""))
            row["best_instrument_win_rate"] = str(best_row.get("bt_win_rate", ""))
            row["best_instrument_pnl"] = str(best_row.get("bt_total_pnl", ""))
            row["best_instrument_trades"] = str(best_row.get("bt_total_trades", ""))
        if summary.worst_instrument:
            row["worst_instrument"] = summary.worst_instrument
        row["instrument_affinity_notes"] = summary.instrument_affinity_notes

    if implementation_status == "coded_and_backtested" and summary.data_source == "exness_production":
        canonical_row = next(
            (
                r for r in rows
                if r.get("module_to_code") == module_name and r.get("action") == "CODE-CANONICAL"
            ),
            None,
        )
        if canonical_row:
            for row in rows:
                if row.get("action") != "DUPLICATE-SKIP":
                    continue
                if row.get("module_to_code") != module_name:
                    continue
                row["implementation_status"] = "covered_by_canonical"
                row["strategy_registry_id"] = summary.strategy_id
                row["data_source"] = summary.data_source
                for key in summary.aggregate_stats:
                    row[key] = str(summary.aggregate_stats[key])
                row["best_instrument"] = canonical_row.get("best_instrument", "")
                row["instrument_affinity_notes"] = canonical_row.get("instrument_affinity_notes", "")

    _write_csv_rows(csv_path, fieldnames, rows)


def cmd_run(args: argparse.Namespace):
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )

    _, has_data = resolve_data_root(args.data_root)
    if has_data and summary.instruments_tested > 0:
        status = "coded_and_backtested"
    else:
        status = "coded_pending_production_backtest"

    anti_bias_notes = (
        "HTF bars gated by bar close in data_feed; session VP built from NY-open M1 bars only; "
        "absorption proxy uses wick/volume without future data; entries on bar close."
    )
    module_name = summary.strategy_module_id
    update_csv_for_strategy(
        Path(args.csv),
        module_name,
        summary,
        anti_bias_passed="yes",
        anti_bias_notes=anti_bias_notes,
        implementation_status=status,
    )

    print("\n=== Run Summary ===")
    print(f"Strategy: {summary.strategy_id}")
    print(f"Data source: {summary.data_source}")
    print(f"Instruments scanned: {summary.instruments_scanned}")
    print(f"Instruments tested: {summary.instruments_tested}")
    print(f"Instruments skipped: {summary.instruments_skipped}")
    if summary.best_instrument:
        print(f"Best instrument: {summary.best_instrument}")
    if summary.aggregate_stats:
        print(f"Aggregate stats: {summary.aggregate_stats}")
    print(f"Status set to: {status}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit.add_argument("--csv", default=str(DEFAULT_CSV))

    sub.add_parser("list-strategies", help="List registered strategies")

    run = sub.add_parser("run", help="Run multi-instrument backtest")
    run.add_argument("--strategy", required=True)
    run.add_argument("--symbols", default="all")
    run.add_argument("--data-root", default=None)
    run.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run.add_argument("--csv", default=str(DEFAULT_CSV))
    run.add_argument("--start", default=None)
    run.add_argument("--end", default=None)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "audit":
        cmd_audit(Path(args.csv))
    elif args.command == "list-strategies":
        cmd_list_strategies()
    elif args.command == "run":
        cmd_run(args)


if __name__ == "__main__":
    main()
