#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, and multi-instrument run.
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

# Ensure backtester package is importable
_DOCS_ROOT = Path(__file__).resolve().parent.parent
if str(_DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(_DOCS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
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
    start_date: str = ""
    end_date: str = ""
    composite_score: float = 0.0
    rank: int = 0
    data_quality_note: str = ""
    skipped: bool = False


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


def resolve_data_root(cli_root: str | None = None) -> tuple[str, bool]:
    """Return (path, exists_with_data)."""
    if cli_root:
        path = Path(cli_root)
        if path.is_dir() and _has_symbol_data(path):
            return str(path), True
        return str(path), False

    env_path = os.getenv("LOCAL_HISTORY_PATH", "")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_data(path):
            return str(path), True

    win_path = Path(DEFAULT_WINDOWS_DATA_ROOT)
    if win_path.is_dir() and _has_symbol_data(win_path):
        return str(win_path), True

    return DEFAULT_WINDOWS_DATA_ROOT, False


def _has_symbol_data(root: Path) -> bool:
    for child in root.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            for tf_dir in child.iterdir():
                if tf_dir.is_dir() and list(tf_dir.glob("*.csv")):
                    return True
    return False


def _load_strategy_config(strategy_cls) -> dict[str, Any]:
    module = strategy_cls.__module__.rsplit(".", 1)[0]
    config_path = Path(sys.modules[module].__file__).parent / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception:
        return {}


def _required_timeframes(strategy_cls) -> list[TF]:
    cfg = _load_strategy_config(strategy_cls)
    tfs = cfg.get("required_timeframes") or [tf.name for tf in strategy_cls.timeframes]
    return [tf_from_string(t) if isinstance(t, str) else t for t in tfs]


def _backtest_defaults(strategy_cls) -> dict[str, float]:
    cfg = _load_strategy_config(strategy_cls)
    return cfg.get("backtest_defaults", {
        "initial_balance": 10000.0,
        "risk_per_trade": 0.01,
        "spread_pips": 1.0,
        "slippage_pips": 0.5,
        "commission_per_lot": 7.0,
    })


def composite_score(row: dict[str, Any], best_pnl: float) -> float:
    pf = min(float(row.get("bt_profit_factor") or 0), 5.0)
    if pf == float("inf"):
        pf = 5.0
    wr = float(row.get("bt_win_rate") or 0)
    sharpe = float(row.get("bt_sharpe_ratio") or 0)
    sharpe_norm = min(max(sharpe, -2), 3) / 3.0
    pnl = float(row.get("bt_total_pnl") or 0)
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    trades = min(int(row.get("bt_total_trades") or 0), 50)
    return round(
        (pf / 5.0 * 0.35)
        + (wr / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (trades / 50.0 * 0.10),
        4,
    )


def run_single_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    data_source: str,
) -> InstrumentResult:
    required_tfs = _required_timeframes(strategy_cls)
    start, end = client.get_full_date_range(symbol, required_tfs)
    if start is None or end is None:
        return InstrumentResult(
            symbol=symbol,
            result=None,
            skipped=True,
            data_quality_note=f"Missing required timeframes: {[t.name for t in required_tfs]}",
        )

    defaults = _backtest_defaults(strategy_cls)
    config = BacktestConfig(
        strategy_id=strategy_cls.id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=defaults.get("initial_balance", 10000.0),
        risk_per_trade=defaults.get("risk_per_trade", 0.01),
        spread_pips=defaults.get("spread_pips", 1.0),
        slippage_pips=defaults.get("slippage_pips", 0.5),
        commission_per_lot=defaults.get("commission_per_lot", 7.0),
    )

    strategy = strategy_cls()
    engine = BacktestEngine(config, strategy, client)
    result = engine.run()

    result_dir = output_dir / strategy_cls.id
    result_dir.mkdir(parents=True, exist_ok=True)
    json_path = result_dir / f"{symbol}.json"
    payload = result.to_dict()
    payload["data_source"] = data_source
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    return InstrumentResult(
        symbol=symbol,
        result=result,
        start_date=start.date().isoformat() if hasattr(start, "date") else str(start)[:10],
        end_date=end.date().isoformat() if hasattr(end, "date") else str(end)[:10],
    )


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path = "results",
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    resolved_root, has_data = resolve_data_root(data_root)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    cfg = _load_strategy_config(strategy_cls)
    module_id = cfg.get("module", strategy_cls.__module__.split(".")[-1])
    video_number = str(cfg.get("video_number", getattr(strategy_cls, "source_video", "")))

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_id,
        video_number=video_number,
        data_root_used=resolved_root,
    )

    if not has_data:
        summary.data_source = "pending_exness_production"
        summary.instrument_affinity_notes = (
            "Production backtest required on Windows with Exness structured history."
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
            instrument_results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=None,
                    skipped=True,
                    data_quality_note="Symbol folder not found under data root",
                )
            )
            continue
        print(f"\n--- Backtesting {symbol} ---")
        ir = run_single_backtest(strategy_cls, symbol, client, output_path, "exness_production")
        instrument_results.append(ir)
        if ir.skipped:
            summary.instruments_skipped += 1
        else:
            summary.instruments_tested += 1

    summary.data_source = "exness_production"
    rows: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for ir in instrument_results:
        if ir.skipped or ir.result is None:
            rows.append({
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": module_id,
                "video_number": video_number,
                "symbol": ir.symbol,
                "data_quality_note": ir.data_quality_note,
                "data_source": "exness_production",
                "backtested_at": now_iso,
                "bt_total_trades": 0,
                "composite_score": 0,
            })
            continue
        r = ir.result
        rows.append({
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_id,
            "video_number": video_number,
            "symbol": ir.symbol,
            "backtest_start_date": ir.start_date,
            "backtest_end_date": ir.end_date,
            "bt_total_trades": r.total_trades,
            "bt_winning_trades": r.winning_trades,
            "bt_losing_trades": r.losing_trades,
            "bt_win_rate": r.win_rate,
            "bt_profit_factor": r.profit_factor,
            "bt_max_drawdown_pct": r.max_drawdown_pct,
            "bt_total_pnl": round(r.total_pnl, 2),
            "bt_sharpe_ratio": r.sharpe_ratio,
            "bt_avg_rr": r.avg_rr,
            "bt_avg_trade_duration_mins": r.avg_trade_duration,
            "backtest_result_json": str(output_path / strategy_cls.id / f"{ir.symbol}.json"),
            "backtested_at": now_iso,
            "data_source": "exness_production",
            "data_quality_note": ir.data_quality_note,
        })

    best_pnl = max((float(r.get("bt_total_pnl") or 0) for r in rows), default=0.0)
    for row in rows:
        row["composite_score"] = composite_score(row, best_pnl)

    ranked = sorted(rows, key=lambda r: r.get("composite_score", 0), reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = rank

    min_trades = int(cfg.get("min_trades_for_ranking", 10))
    eligible = [r for r in ranked if int(r.get("bt_total_trades") or 0) >= min_trades]
    if eligible:
        best = eligible[0]
        worst = eligible[-1]
        summary.best_instrument = best["symbol"]
        summary.worst_instrument = worst["symbol"]
        summary.instrument_affinity_notes = (
            f"Strong on {best['symbol']} (PF={best.get('bt_profit_factor')}, "
            f"{best.get('bt_total_trades')} trades). "
            f"Weak on {worst['symbol']} (PF={worst.get('bt_profit_factor')})."
        )

    summary.matrix_rows = ranked
    summary.aggregate_stats = _aggregate_stats(ranked)
    _update_matrix_csv(output_path / "strategy_instrument_matrix.csv", ranked)
    return summary


def _aggregate_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tested = [r for r in rows if int(r.get("bt_total_trades") or 0) > 0]
    if not tested:
        return {
            "bt_total_trades_all": 0,
            "bt_win_rate_all": 0,
            "bt_profit_factor_all": 0,
            "bt_max_drawdown_pct_all": 0,
            "bt_total_pnl_all": 0,
            "bt_sharpe_ratio_all": 0,
            "bt_avg_rr_all": 0,
        }
    total_trades = sum(int(r.get("bt_total_trades") or 0) for r in tested)
    total_wins = sum(int(r.get("bt_winning_trades") or 0) for r in tested)
    gross_profit = sum(float(r.get("bt_total_pnl") or 0) for r in tested if float(r.get("bt_total_pnl") or 0) > 0)
    gross_loss = abs(sum(float(r.get("bt_total_pnl") or 0) for r in tested if float(r.get("bt_total_pnl") or 0) < 0))
    return {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0,
        "bt_profit_factor_all": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
        "bt_max_drawdown_pct_all": round(max(float(r.get("bt_max_drawdown_pct") or 0) for r in tested), 2),
        "bt_total_pnl_all": round(sum(float(r.get("bt_total_pnl") or 0) for r in tested), 2),
        "bt_sharpe_ratio_all": round(
            sum(float(r.get("bt_sharpe_ratio") or 0) for r in tested) / len(tested), 2
        ),
        "bt_avg_rr_all": round(
            sum(float(r.get("bt_avg_rr") or 0) for r in tested) / len(tested), 2
        ),
    }


def _update_matrix_csv(matrix_path: Path, new_rows: list[dict[str, Any]]) -> None:
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if matrix_path.exists():
        with open(matrix_path, "r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for row in new_rows:
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        merged = existing.get(key, {})
        merged.update({k: v for k, v in row.items() if v is not None})
        existing[key] = merged

    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    with open(matrix_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in existing.values():
            writer.writerow(row)


def _read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=csv_path.parent, suffix=".csv.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, csv_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def audit_csv(csv_path: Path) -> dict[str, Any]:
    fieldnames, rows = _read_csv_rows(csv_path)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    coded_folders = {
        p.name
        for p in (Path(__file__).parent / "strategies").iterdir()
        if p.is_dir() and p.name not in ("__pycache__",)
    }
    registered = set(list_strategy_ids())

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")
    pending = [
        r for r in canonical
        if r.get("implementation_status", "") in ("", "not_started", "failed", "in_progress")
    ]
    pending.sort(key=lambda r: int(r.get("video_number") or 999))

    return {
        "csv_path": str(csv_path),
        "canonical_total": len(canonical),
        "canonical_done": done,
        "coded_folders": sorted(coded_folders),
        "registered_strategies": sorted(registered),
        "next_pending": pending[0] if pending else None,
        "fieldnames": fieldnames,
        "rows": rows,
    }


def update_tracking_csv(
    csv_path: Path,
    module_to_code: str,
    updates: dict[str, Any],
    propagate_duplicates: bool = False,
) -> None:
    fieldnames, rows = _read_csv_rows(csv_path)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for row in rows:
        if row.get("module_to_code") == module_to_code and row.get("action") == "CODE-CANONICAL":
            row.update({k: str(v) if v is not None else "" for k, v in updates.items()})
            if updates.get("implementation_status") == "coded" and not row.get("coded_at"):
                row["coded_at"] = now_iso
            if updates.get("implementation_status") == "coded_and_backtested" and not row.get("backtested_at"):
                row["backtested_at"] = now_iso

        if propagate_duplicates and row.get("duplicate_of_video"):
            dup_of = row.get("duplicate_of_video", "")
            canonical_row = next(
                (r for r in rows if r.get("video_number") == dup_of and r.get("action") == "CODE-CANONICAL"),
                None,
            )
            if canonical_row and canonical_row.get("module_to_code") == module_to_code:
                if canonical_row.get("implementation_status") == "coded_and_backtested":
                    row["implementation_status"] = "covered_by_canonical"
                    for col in TRACKING_COLUMNS:
                        if col.startswith("bt_") or col.startswith("best_") or col == "worst_instrument":
                            row[col] = canonical_row.get(col, "")

    _write_csv_atomic(csv_path, fieldnames, rows)


def cmd_audit(args: argparse.Namespace) -> int:
    report = audit_csv(Path(args.csv))
    print(f"Canonical progress: {report['canonical_done']}/{report['canonical_total']}")
    print(f"Coded folders: {', '.join(report['coded_folders']) or '(none)'}")
    print(f"Registered: {', '.join(report['registered_strategies']) or '(none)'}")
    if report["next_pending"]:
        n = report["next_pending"]
        print(f"Next pending: Video #{n.get('video_number')} — {n.get('title')} ({n.get('module_to_code')})")
    else:
        print("Pipeline complete.")
    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    for sid in list_strategy_ids():
        cls = get_strategy(sid)
        print(f"{sid}: {cls.name if cls else '?'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    print(f"\nData source: {summary.data_source}")
    print(f"Instruments scanned: {summary.instruments_scanned}")
    print(f"Instruments tested: {summary.instruments_tested}")
    print(f"Instruments skipped: {summary.instruments_skipped}")
    if summary.best_instrument:
        print(f"Best: {summary.best_instrument}")
        print(f"Worst: {summary.worst_instrument}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit CSV vs coded folders")
    audit_p.add_argument("--csv", required=True)

    sub.add_parser("list-strategies", help="List registered strategies")

    run_p = sub.add_parser("run", help="Run multi-instrument backtest")
    run_p.add_argument("--strategy", required=True)
    run_p.add_argument("--symbols", default="all")
    run_p.add_argument("--data-root", default=None)
    run_p.add_argument("--output", default=str(Path(__file__).parent / "results"))
    run_p.add_argument("--start", default=None)
    run_p.add_argument("--end", default=None)

    args = parser.parse_args()
    if args.command == "audit":
        return cmd_audit(args)
    if args.command == "list-strategies":
        return cmd_list_strategies(args)
    if args.command == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
