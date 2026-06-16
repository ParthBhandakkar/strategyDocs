#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, and multi-instrument runs.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"

if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient, resolve_data_root
from backtester.core import BacktestConfig
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
class InstrumentResult:
    symbol: str
    stats: dict[str, Any]
    composite_score: float = 0.0
    rank: int = 0
    data_quality_note: str = ""
    result_path: str = ""


@dataclass
class MultiBacktestSummary:
    strategy_id: str
    strategy_module: str
    video_number: str
    data_source: str
    data_root: str
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: Optional[str] = None
    worst_instrument: Optional[str] = None
    affinity_notes: str = ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_yaml_defaults(strategy_module: str) -> dict[str, Any]:
    import yaml

    cfg_path = BACKTESTER_ROOT / "strategies" / strategy_module / "config.yaml"
    if not cfg_path.exists():
        return {}
    with cfg_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _required_timeframes(strategy_cls) -> list[TF]:
    cfg = _load_yaml_defaults(strategy_cls.id.split("_", 1)[-1])
    req = cfg.get("required_timeframes") or []
    if req:
        return [tf_from_string(x) for x in req]
    return list(strategy_cls.timeframes)


def _composite_score(stats: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(stats.get("total_trades", 0))
    if trades < min_trades:
        return 0.0
    pf = min(float(stats.get("profit_factor", 0) or 0), 5.0)
    win_rate = float(stats.get("win_rate", 0) or 0)
    sharpe = float(stats.get("sharpe_ratio", 0) or 0)
    pnl = float(stats.get("total_pnl", 0) or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    pnl_norm = min(max(pnl_norm, 0.0), 1.0)
    trade_norm = min(trades, 50) / 50.0
    return round(
        (pf / 5.0 * 0.35)
        + (win_rate / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (trade_norm * 0.10),
        4,
    )


def run_single_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    data_source: str,
) -> tuple[Optional[dict[str, Any]], str]:
    required_tfs = _required_timeframes(strategy_cls)
    for tf in required_tfs:
        if not client.has_timeframe(symbol, tf):
            return None, f"missing timeframe {tf.name}"

    start, end = client.get_full_date_range(symbol, required_tfs)
    if not start or not end or start >= end:
        return None, "no overlapping date range"

    module = strategy_cls.id.split("_", 1)[-1]
    cfg = _load_yaml_defaults(module)
    defaults = cfg.get("backtest_defaults", {})

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
    result_dict = result.to_dict()
    result_dict["data_source"] = data_source

    strat_out = output_dir / strategy_cls.id
    strat_out.mkdir(parents=True, exist_ok=True)
    json_path = strat_out / f"{symbol}.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(result_dict, handle, indent=2)

    stats = result_dict["stats"]
    stats["backtest_start_date"] = start.date().isoformat()
    stats["backtest_end_date"] = end.date().isoformat()
    stats["backtest_result_json"] = str(json_path.relative_to(BACKTESTER_ROOT))
    return stats, ""


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiBacktestSummary:
    del start, end  # full range per symbol by default

    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    resolved = resolve_data_root(str(data_root) if data_root else None)
    data_source = "exness_production" if resolved else "not_backtested"
    client = ExnessCSVClient(resolved) if resolved else None

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module = strategy_cls.id.split("_", 1)[-1]
    cfg = _load_yaml_defaults(module)
    video_number = str(cfg.get("video_number", ""))

    summary = MultiBacktestSummary(
        strategy_id=strategy_cls.id,
        strategy_module=module,
        video_number=video_number,
        data_source=data_source if resolved else "pending_exness_production",
        data_root=str(resolved) if resolved else "",
    )

    if client is None:
        summary.instruments_skipped = 0
        summary.affinity_notes = "Production backtest required on Windows with Exness history path."
        return summary

    if symbols == "all":
        symbol_list = client.get_symbols()
    elif isinstance(symbols, str):
        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        symbol_list = [s.upper() for s in symbols]

    summary.instruments_scanned = len(symbol_list)
    instrument_results: list[InstrumentResult] = []

    for symbol in symbol_list:
        stats, note = run_single_backtest(
            strategy_cls, symbol, client, output_path, data_source
        )
        if stats is None:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = note
            continue
        summary.instruments_tested += 1
        instrument_results.append(
            InstrumentResult(symbol=symbol, stats=stats, data_quality_note=note)
        )

    if instrument_results:
        best_pnl = max(float(r.stats.get("total_pnl", 0) or 0) for r in instrument_results)
        best_pnl = max(best_pnl, 1e-9)
        for item in instrument_results:
            item.composite_score = _composite_score(item.stats, best_pnl)

        ranked = sorted(
            instrument_results,
            key=lambda r: r.composite_score,
            reverse=True,
        )
        for idx, item in enumerate(ranked, start=1):
            item.rank = idx

        eligible = [r for r in ranked if int(r.stats.get("total_trades", 0)) >= 10]
        if eligible:
            summary.best_instrument = eligible[0].symbol
            summary.worst_instrument = eligible[-1].symbol

        summary.aggregate_stats = _aggregate_stats(instrument_results)
        summary.affinity_notes = _build_affinity_notes(ranked)
        summary.matrix_rows = _build_matrix_rows(
            strategy_cls.id,
            module,
            video_number,
            ranked,
            data_source,
        )
        _update_matrix_csv(output_path / "strategy_instrument_matrix.csv", summary.matrix_rows)

    return summary


def _aggregate_stats(results: list[InstrumentResult]) -> dict[str, Any]:
    total_trades = sum(int(r.stats.get("total_trades", 0)) for r in results)
    total_wins = sum(int(r.stats.get("winning_trades", 0)) for r in results)
    total_pnl = sum(float(r.stats.get("total_pnl", 0) or 0) for r in results)
    win_rate = round(total_wins / total_trades * 100, 2) if total_trades else 0.0

    gross_profit = sum(
        float(r.stats.get("total_pnl", 0))
        for r in results
        if float(r.stats.get("total_pnl", 0)) > 0
    )
    gross_loss = abs(
        sum(
            float(r.stats.get("total_pnl", 0))
            for r in results
            if float(r.stats.get("total_pnl", 0)) <= 0
        )
    )
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0
    max_dd = max(float(r.stats.get("max_drawdown_pct", 0) or 0) for r in results) if results else 0.0
    sharpe_vals = [float(r.stats.get("sharpe_ratio", 0) or 0) for r in results if r.stats.get("total_trades")]
    avg_rr_vals = [float(r.stats.get("avg_rr", 0) or 0) for r in results if r.stats.get("total_trades")]
    sharpe = round(sum(sharpe_vals) / len(sharpe_vals), 2) if sharpe_vals else 0.0
    avg_rr = round(sum(avg_rr_vals) / len(avg_rr_vals), 2) if avg_rr_vals else 0.0

    return {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": win_rate,
        "bt_profit_factor_all": pf,
        "bt_max_drawdown_pct_all": max_dd,
        "bt_total_pnl_all": round(total_pnl, 2),
        "bt_sharpe_ratio_all": sharpe,
        "bt_avg_rr_all": avg_rr,
    }


def _build_affinity_notes(ranked: list[InstrumentResult]) -> str:
    strong = [
        r for r in ranked
        if r.composite_score > 0 and float(r.stats.get("profit_factor", 0) or 0) >= 1.2
    ][:3]
    weak = [
        r for r in reversed(ranked)
        if int(r.stats.get("total_trades", 0)) >= 10
        and float(r.stats.get("profit_factor", 0) or 0) < 1.0
    ][:3]
    parts = []
    if strong:
        syms = ", ".join(f"{r.symbol}(PF={r.stats.get('profit_factor')})" for r in strong)
        parts.append(f"Stronger on {syms}.")
    if weak:
        syms = ", ".join(r.symbol for r in weak)
        parts.append(f"Weaker on {syms}.")
    if not parts:
        return "No instrument reached 10+ trades for ranking; strategy may need production NQ-like volatility."
    return " ".join(parts)


def _build_matrix_rows(
    strategy_id: str,
    module: str,
    video_number: str,
    ranked: list[InstrumentResult],
    data_source: str,
) -> list[dict[str, Any]]:
    now = _utc_now_iso()
    rows = []
    for item in ranked:
        stats = item.stats
        rows.append({
            "strategy_registry_id": strategy_id,
            "strategy_module_id": module,
            "video_number": video_number,
            "symbol": item.symbol,
            "backtest_start_date": stats.get("backtest_start_date", ""),
            "backtest_end_date": stats.get("backtest_end_date", ""),
            "bt_total_trades": stats.get("total_trades", 0),
            "bt_winning_trades": stats.get("winning_trades", 0),
            "bt_losing_trades": stats.get("losing_trades", 0),
            "bt_win_rate": stats.get("win_rate", 0),
            "bt_profit_factor": stats.get("profit_factor", 0),
            "bt_max_drawdown_pct": stats.get("max_drawdown_pct", 0),
            "bt_total_pnl": stats.get("total_pnl", 0),
            "bt_sharpe_ratio": stats.get("sharpe_ratio", 0),
            "bt_avg_rr": stats.get("avg_rr", 0),
            "bt_avg_trade_duration_mins": stats.get("avg_trade_duration_mins", 0),
            "composite_score": item.composite_score,
            "rank_within_strategy": item.rank,
            "backtest_result_json": stats.get("backtest_result_json", ""),
            "backtested_at": now,
            "data_quality_note": item.data_quality_note,
            "data_source": data_source,
        })
    return rows


def _update_matrix_csv(path: Path, new_rows: list[dict[str, Any]]):
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row
    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = row
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in existing.values():
            writer.writerow(row)
    tmp.replace(path)


def _ensure_csv_columns(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
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


def _write_csv_atomic(csv_path: Path, rows: list[dict[str, str]], fieldnames: list[str]):
    tmp = csv_path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(csv_path)


def cmd_audit(csv_path: Path):
    rows, fieldnames = _ensure_csv_columns(csv_path)
    coded_modules = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and (p / "strategy.py").exists()
    }
    registry = load_all_strategies()
    data_root = resolve_data_root()
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_root else 0

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")
    pending = sum(
        1 for r in canonical
        if r.get("implementation_status") in ("", "not_started", "in_progress", "failed")
    )

    print("=== Backtester Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Data root: {data_root or 'NOT AVAILABLE'}")
    print(f"Symbols available: {symbol_count}")
    print(f"Registry strategies: {len(registry)} -> {sorted(registry.keys())}")
    print(f"Coded folders: {sorted(coded_modules)}")
    print(f"Canonical progress: {done}/{len(canonical)} coded_and_backtested, {pending} pending")
    _write_csv_atomic(csv_path, rows, fieldnames)


def cmd_list_strategies():
    registry = load_all_strategies()
    if not registry:
        print("No strategies registered.")
        return
    for strat_id, cls in sorted(registry.items()):
        print(f"{strat_id}\t{cls.name}\t{[tf.name for tf in cls.timeframes]}")


def cmd_run(args):
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    print(json.dumps({
        "strategy_id": summary.strategy_id,
        "data_source": summary.data_source,
        "instruments_scanned": summary.instruments_scanned,
        "instruments_tested": summary.instruments_tested,
        "instruments_skipped": summary.instruments_skipped,
        "best_instrument": summary.best_instrument,
        "worst_instrument": summary.worst_instrument,
        "aggregate_stats": summary.aggregate_stats,
    }, indent=2))
    return summary


def update_strategy_csv_row(
    csv_path: Path,
    module: str,
    updates: dict[str, str],
    duplicate_canonical: bool = False,
):
    rows, fieldnames = _ensure_csv_columns(csv_path)
    for row in rows:
        if row.get("module_to_code") == module and row.get("action") == "CODE-CANONICAL":
            row.update(updates)
        elif duplicate_canonical and row.get("module_to_code") == module and row.get("action") == "DUPLICATE-SKIP":
            row.update({k: v for k, v in updates.items() if k.startswith("bt_") or k in (
                "implementation_status", "best_instrument", "worst_instrument",
                "instrument_affinity_notes", "data_source", "backtested_at",
            )})
            if updates.get("implementation_status") == "coded_and_backtested":
                row["implementation_status"] = "covered_by_canonical"
    _write_csv_atomic(csv_path, rows, fieldnames)


def main():
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

    args = parser.parse_args()
    if args.command == "audit":
        cmd_audit(Path(args.csv))
    elif args.command == "list-strategies":
        cmd_list_strategies()
    elif args.command == "run":
        cmd_run(args)


if __name__ == "__main__":
    main()
