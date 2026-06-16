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

ROOT = Path(__file__).resolve().parent
DOCUMENTS = ROOT.parent
if str(DOCUMENTS) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies

DEFAULT_WINDOWS_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
DEFAULT_CSV = DOCUMENTS / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = ROOT / "results"
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
    start_date: str
    end_date: str
    stats: dict[str, Any]
    composite_score: float = 0.0
    rank_within_strategy: int = 0
    data_quality_note: str = ""
    json_path: str = ""


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    module_id: str
    video_number: str
    best_instrument: str = ""
    worst_instrument: str = ""
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_root: str | None = None) -> tuple[str, bool]:
    if cli_root:
        path = Path(cli_root)
        if path.is_dir() and _has_symbol_folders(path):
            return str(path), True
        return str(path), False

    env_path = os.getenv("LOCAL_HISTORY_PATH", "").strip()
    if env_path and Path(env_path).is_dir() and _has_symbol_folders(Path(env_path)):
        return env_path, True

    default = Path(DEFAULT_WINDOWS_DATA_ROOT)
    if default.is_dir() and _has_symbol_folders(default):
        return str(default), True

    return env_path or DEFAULT_WINDOWS_DATA_ROOT, False


def _has_symbol_folders(path: Path) -> bool:
    if not path.is_dir():
        return False
    for entry in path.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            return True
    return False


def _load_yaml_defaults(strategy_cls) -> dict[str, Any]:
    module_parts = strategy_cls.__module__.split(".")
    folder = module_parts[-2] if module_parts[-1] == "strategy" else module_parts[-1]
    config_path = ROOT / "strategies" / folder / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _required_timeframes(strategy_cls) -> list[TF]:
    cfg = _load_yaml_defaults(strategy_cls)
    raw = cfg.get("required_timeframes") or [tf.name for tf in strategy_cls.timeframes]
    return [tf_from_string(item) if isinstance(item, str) else item for item in raw]


def _backtest_defaults(strategy_cls) -> dict[str, float]:
    cfg = _load_yaml_defaults(strategy_cls)
    defaults = cfg.get("backtest_defaults") or {}
    return {
        "initial_balance": float(defaults.get("initial_balance", 10000.0)),
        "risk_per_trade": float(defaults.get("risk_per_trade", 0.01)),
        "spread_pips": float(defaults.get("spread_pips", 1.0)),
        "slippage_pips": float(defaults.get("slippage_pips", 0.5)),
        "commission_per_lot": float(defaults.get("commission_per_lot", 7.0)),
    }


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
    return (
        (pf / 5.0 * 0.35)
        + (win_rate / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10)
    )


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str,
    symbols: str | list[str] = "all",
    output_dir: str | Path = DEFAULT_OUTPUT,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> MultiInstrumentSummary:
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    strategy = strategy_cls()
    module_id = strategy_id.split("_", 1)[-1] if "_" in strategy_id else strategy_id
    cfg_defaults = _backtest_defaults(strategy_cls)
    required_tfs = _required_timeframes(strategy_cls)
    client = ExnessCSVClient(data_root)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    strategy_output = output_path / strategy.id
    strategy_output.mkdir(parents=True, exist_ok=True)

    if symbols == "all":
        symbol_list = client.get_symbols()
    elif isinstance(symbols, str):
        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        symbol_list = [s.upper() for s in symbols]

    summary = MultiInstrumentSummary(
        strategy_id=strategy.id,
        module_id=module_id,
        video_number=strategy.source_video,
        instruments_scanned=len(symbol_list),
        data_root_used=data_root,
        data_source="exness_production",
    )

    instrument_results: list[InstrumentResult] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for symbol in symbol_list:
        start_date, end_date = client.get_full_date_range(symbol, required_tfs)
        if start_date is None or end_date is None:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = "missing required timeframe data"
            continue

        run_start = start or start_date
        run_end = end or end_date
        config = BacktestConfig(
            strategy_id=strategy.id,
            symbol=symbol,
            start_date=run_start,
            end_date=run_end,
            initial_balance=cfg_defaults["initial_balance"],
            risk_per_trade=cfg_defaults["risk_per_trade"],
            spread_pips=cfg_defaults["spread_pips"],
            slippage_pips=cfg_defaults["slippage_pips"],
            commission_per_lot=cfg_defaults["commission_per_lot"],
        )

        try:
            engine = BacktestEngine(config, strategy_cls(), client)
            result = engine.run()
        except Exception as exc:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = str(exc)
            continue

        json_path = strategy_output / f"{symbol}.json"
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle, indent=2)

        stats = result.to_dict()["stats"]
        instrument_results.append(
            InstrumentResult(
                symbol=symbol,
                start_date=run_start.date().isoformat(),
                end_date=run_end.date().isoformat(),
                stats=stats,
                json_path=str(json_path),
            )
        )
        summary.instruments_tested += 1

    best_pnl = max((r.stats.get("total_pnl", 0) for r in instrument_results), default=0.0)
    min_trades = int(_load_yaml_defaults(strategy_cls).get("min_trades_for_ranking", 10))

    rows: list[dict[str, Any]] = []
    for item in instrument_results:
        row = {
            "strategy_registry_id": strategy.id,
            "strategy_module_id": module_id,
            "video_number": strategy.source_video,
            "symbol": item.symbol,
            "backtest_start_date": item.start_date,
            "backtest_end_date": item.end_date,
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
            "backtest_result_json": item.json_path,
            "backtested_at": now_iso,
            "data_quality_note": "",
            "data_source": "exness_production",
        }
        row["composite_score"] = round(composite_score(row, best_pnl, min_trades), 4)
        rows.append(row)

    ranked = sorted(rows, key=lambda r: r["composite_score"], reverse=True)
    for idx, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = idx

    summary.matrix_rows = rows
    summary.aggregate_stats = _aggregate_stats(rows)

    eligible = [r for r in rows if int(r["bt_total_trades"]) >= min_trades]
    if eligible:
        best = max(eligible, key=lambda r: r["composite_score"])
        worst = min(eligible, key=lambda r: r["composite_score"])
        summary.best_instrument = best["symbol"]
        summary.worst_instrument = worst["symbol"]

    _write_matrix_csv(rows)
    return summary


def _aggregate_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    total_trades = sum(int(r.get("bt_total_trades", 0)) for r in rows)
    total_pnl = sum(float(r.get("bt_total_pnl", 0) or 0) for r in rows)
    wins = sum(int(r.get("bt_winning_trades", 0)) for r in rows)
    win_rate = round(wins / total_trades * 100, 2) if total_trades else 0.0
    gross_profit = sum(float(r.get("bt_total_pnl", 0) or 0) for r in rows if float(r.get("bt_total_pnl", 0) or 0) > 0)
    gross_loss = abs(sum(float(r.get("bt_total_pnl", 0) or 0) for r in rows if float(r.get("bt_total_pnl", 0) or 0) <= 0))
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")
    max_dd = max(float(r.get("bt_max_drawdown_pct", 0) or 0) for r in rows) if rows else 0.0
    sharpe_vals = [float(r.get("bt_sharpe_ratio", 0) or 0) for r in rows if int(r.get("bt_total_trades", 0)) > 0]
    avg_sharpe = round(sum(sharpe_vals) / len(sharpe_vals), 2) if sharpe_vals else 0.0
    rr_vals = [float(r.get("bt_avg_rr", 0) or 0) for r in rows if int(r.get("bt_total_trades", 0)) > 0]
    avg_rr = round(sum(rr_vals) / len(rr_vals), 2) if rr_vals else 0.0
    return {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": win_rate,
        "bt_profit_factor_all": pf,
        "bt_max_drawdown_pct_all": max_dd,
        "bt_total_pnl_all": round(total_pnl, 2),
        "bt_sharpe_ratio_all": avg_sharpe,
        "bt_avg_rr_all": avg_rr,
    }


def _write_matrix_csv(new_rows: list[dict[str, Any]]) -> None:
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if MATRIX_CSV.exists():
        with open(MATRIX_CSV, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row
    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {col: str(row.get(col, "")) for col in MATRIX_COLUMNS}
    with open(MATRIX_CSV, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda r: (r["strategy_registry_id"], r["symbol"])):
            writer.writerow(row)


def _ensure_csv_columns(csv_path: Path) -> list[str]:
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

    _write_csv_atomic(csv_path, fieldnames, rows)
    return fieldnames


def _write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8") as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        temp_name = tmp.name
    os.replace(temp_name, csv_path)


def audit_csv(csv_path: Path) -> dict[str, Any]:
    fieldnames = _ensure_csv_columns(csv_path)
    with open(csv_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    coded_folders = [
        p.name
        for p in (ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__"}
        and (p / "strategy.py").exists()
    ]
    registry = load_all_strategies()
    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")
    pending = [
        r for r in canonical
        if r.get("implementation_status", "") in ("", "not_started", "failed", "in_progress")
    ]
    pending.sort(key=lambda r: int(r.get("video_number", 9999)))

    data_root, data_ok = resolve_data_root()
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_ok else 0

    return {
        "csv_path": str(csv_path),
        "canonical_total": len(canonical),
        "canonical_done": done,
        "coded_folders": coded_folders,
        "registered_strategies": list(registry.keys()),
        "data_root": data_root,
        "data_available": data_ok,
        "symbol_count": symbol_count,
        "next_pending": pending[0] if pending else None,
    }


def cmd_audit(args: argparse.Namespace) -> None:
    report = audit_csv(Path(args.csv))
    print(json.dumps(report, indent=2))


def cmd_list_strategies(_: argparse.Namespace) -> None:
    for cls in get_all_strategies():
        print(f"{cls.id}\t{cls.name}\t{cls.__module__}")


def cmd_run(args: argparse.Namespace) -> None:
    data_root, data_ok = resolve_data_root(args.data_root)
    if not data_ok:
        print(f"WARNING: Real Exness data not found at {data_root}")
        print("Implementations can be coded but backtests require production data on Windows.")
        return

    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    print(json.dumps(
        {
            "strategy_id": summary.strategy_id,
            "instruments_tested": summary.instruments_tested,
            "best_instrument": summary.best_instrument,
            "worst_instrument": summary.worst_instrument,
            "aggregate_stats": summary.aggregate_stats,
        },
        indent=2,
    ))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Faiz SMC Strategy Backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit CSV vs coded folders vs data")
    audit_p.add_argument("--csv", default=str(DEFAULT_CSV))
    audit_p.set_defaults(func=cmd_audit)

    list_p = sub.add_parser("list-strategies", help="List registered strategies")
    list_p.set_defaults(func=cmd_list_strategies)

    run_p = sub.add_parser("run", help="Run multi-instrument backtest")
    run_p.add_argument("--strategy", required=True)
    run_p.add_argument("--symbols", default="all")
    run_p.add_argument("--data-root", default=None)
    run_p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_p.set_defaults(func=cmd_run)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
