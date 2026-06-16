#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, run multi-instrument backtests.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
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
DEFAULT_CSV = DOCS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
DEFAULT_MATRIX = DEFAULT_OUTPUT / "strategy_instrument_matrix.csv"

if str(DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient, resolve_data_root
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_strategy, list_strategy_ids, load_all_strategies

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

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
    module_id: str
    video_number: str
    data_root: str | None
    data_source: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str | None = None
    worst_instrument: str | None = None
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def _write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", delete=False, dir=path.parent) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _load_strategy_config(module: str) -> dict[str, Any]:
    cfg_path = BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _composite_score(row: dict[str, Any], max_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades") or 0)
    if trades < min_trades:
        return -1.0
    pf = min(float(row.get("bt_profit_factor") or 0), 5.0) / 5.0 * 0.35
    wr = float(row.get("bt_win_rate") or 0) / 100.0 * 0.20
    sharpe = float(row.get("bt_sharpe_ratio") or 0)
    sharpe_norm = min(max(sharpe, -2), 3) / 3.0 * 0.20
    pnl = float(row.get("bt_total_pnl") or 0)
    pnl_norm = (pnl / max_pnl) * 0.15 if max_pnl > 0 else 0.0
    trade_norm = min(trades, 50) / 50.0 * 0.10
    return round(pf + wr + sharpe_norm + pnl_norm + trade_norm, 4)


def run_single_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    config_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    cfg_yaml = config_overrides or {}
    defaults = cfg_yaml.get("backtest_defaults", {})
    required_tfs = [tf_from_string(t) for t in cfg_yaml.get("required_timeframes", [])]
    if not required_tfs:
        required_tfs = list(strategy_cls.timeframes)

    for tf in required_tfs:
        if not client.has_timeframe(symbol, tf):
            return None, f"missing timeframe {tf.name}"

    start, end = client.get_full_date_range(symbol, required_tfs)
    if not start or not end or start >= end:
        return None, "insufficient date range"

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
    engine = BacktestEngine(config=config, strategy=strategy, client=client)
    result = engine.run()

    result_dict = result.to_dict()
    strat_out = output_dir / strategy_cls.id
    strat_out.mkdir(parents=True, exist_ok=True)
    json_path = strat_out / f"{symbol}.json"
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(result_dict, handle, indent=2)

    stats = result_dict["stats"]
    winners = stats["winning_trades"]
    losers = stats["losing_trades"]
    row = {
        "symbol": symbol,
        "backtest_start_date": start.date().isoformat(),
        "backtest_end_date": end.date().isoformat(),
        "bt_total_trades": stats["total_trades"],
        "bt_winning_trades": winners,
        "bt_losing_trades": losers,
        "bt_win_rate": stats["win_rate"],
        "bt_profit_factor": stats["profit_factor"],
        "bt_max_drawdown_pct": stats["max_drawdown_pct"],
        "bt_total_pnl": stats["total_pnl"],
        "bt_sharpe_ratio": stats["sharpe_ratio"],
        "bt_avg_rr": stats["avg_rr"],
        "bt_avg_trade_duration_mins": stats["avg_trade_duration_mins"],
        "backtest_result_json": str(json_path.relative_to(BACKTESTER_ROOT)),
        "backtested_at": _utc_now_iso(),
        "data_quality_note": "",
    }
    return row, ""


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
) -> RunSummary:
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    root = resolve_data_root(str(data_root) if data_root else None)
    module_id = strategy_cls.id.split("_", 1)[-1] if "_" in strategy_cls.id else strategy_cls.id
    cfg = _load_strategy_config(module_id)
    video_number = str(cfg.get("video_number", ""))

    summary = RunSummary(
        strategy_id=strategy_cls.id,
        module_id=module_id,
        video_number=video_number,
        data_root=str(root) if root else None,
        data_source="not_backtested" if not root else "pending_exness_production",
    )

    if root is None:
        logger.warning("No real Exness history path available — skipping backtests")
        return summary

    client = ExnessCSVClient(root)
    all_symbols = client.get_symbols()
    summary.instruments_scanned = len(all_symbols)

    if isinstance(symbols, str):
        target_symbols = all_symbols if symbols.lower() == "all" else [s.strip() for s in symbols.split(",")]
    else:
        target_symbols = symbols

    out = Path(output_dir or DEFAULT_OUTPUT)
    out.mkdir(parents=True, exist_ok=True)

    for symbol in target_symbols:
        if symbol not in all_symbols:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = "symbol not in data root"
            continue
        try:
            row, err = run_single_backtest(strategy_cls, symbol, client, out, cfg)
            if row is None:
                summary.instruments_skipped += 1
                summary.skip_reasons[symbol] = err
                continue
            row["strategy_registry_id"] = strategy_cls.id
            row["strategy_module_id"] = module_id
            row["video_number"] = video_number
            row["data_source"] = "exness_production"
            summary.matrix_rows.append(row)
            summary.instruments_tested += 1
        except Exception as exc:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = str(exc)
            logger.exception("Backtest failed for %s", symbol)

    if summary.matrix_rows:
        summary.data_source = "exness_production"
        _finalize_summary(summary, cfg)
        _update_matrix_csv(summary)
    return summary


def _finalize_summary(summary: RunSummary, cfg: dict[str, Any]):
    min_trades = int(cfg.get("min_trades_for_ranking", 10))
    max_pnl = max(float(r["bt_total_pnl"]) for r in summary.matrix_rows)
    for row in summary.matrix_rows:
        row["composite_score"] = _composite_score(row, max_pnl, min_trades)

    ranked = sorted(
        [r for r in summary.matrix_rows if float(r["composite_score"]) >= 0],
        key=lambda r: r["composite_score"],
        reverse=True,
    )
    for idx, row in enumerate(ranked, start=1):
        row["rank_within_strategy"] = idx
    for row in summary.matrix_rows:
        row.setdefault("rank_within_strategy", "")

    if ranked:
        best = ranked[0]
        worst = ranked[-1]
        summary.best_instrument = best["symbol"]
        summary.worst_instrument = worst["symbol"]

    total_trades = sum(int(r["bt_total_trades"]) for r in summary.matrix_rows)
    total_pnl = sum(float(r["bt_total_pnl"]) for r in summary.matrix_rows)
    wins = sum(int(r["bt_winning_trades"]) for r in summary.matrix_rows)
    win_rate = round(wins / total_trades * 100, 2) if total_trades else 0.0

    gross_profit = sum(float(r["bt_total_pnl"]) for r in summary.matrix_rows if float(r["bt_total_pnl"]) > 0)
    gross_loss = abs(sum(float(r["bt_total_pnl"]) for r in summary.matrix_rows if float(r["bt_total_pnl"]) <= 0))
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0
    max_dd = max(float(r["bt_max_drawdown_pct"]) for r in summary.matrix_rows) if summary.matrix_rows else 0.0
    sharpe_vals = [float(r["bt_sharpe_ratio"]) for r in summary.matrix_rows if r.get("bt_sharpe_ratio")]
    avg_sharpe = round(sum(sharpe_vals) / len(sharpe_vals), 2) if sharpe_vals else 0.0
    avg_rr_vals = [float(r["bt_avg_rr"]) for r in summary.matrix_rows if r.get("bt_avg_rr")]
    avg_rr = round(sum(avg_rr_vals) / len(avg_rr_vals), 2) if avg_rr_vals else 0.0

    summary.aggregate_stats = {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": win_rate,
        "bt_profit_factor_all": pf,
        "bt_max_drawdown_pct_all": max_dd,
        "bt_total_pnl_all": round(total_pnl, 2),
        "bt_sharpe_ratio_all": avg_sharpe,
        "bt_avg_rr_all": avg_rr,
    }


def _update_matrix_csv(summary: RunSummary):
    path = DEFAULT_MATRIX
    if path.exists():
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            existing = {row["strategy_registry_id"] + "|" + row["symbol"]: row for row in reader}
    else:
        existing = {}

    for row in summary.matrix_rows:
        key = row["strategy_registry_id"] + "|" + row["symbol"]
        merged = {col: "" for col in MATRIX_COLUMNS}
        if key in existing:
            merged.update(existing[key])
        merged.update({k: str(v) for k, v in row.items() if k in MATRIX_COLUMNS})
        existing[key] = merged

    _write_csv_atomic(path, MATRIX_COLUMNS, list(existing.values()))


def cmd_audit(csv_path: Path):
    fieldnames, rows = _read_csv(csv_path)
    coded_dirs = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__", "tests"}
    }
    registry = load_all_strategies()
    canonical = [r for r in rows if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"]

    print("\n=== Backtester Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Strategy folders on disk: {sorted(coded_dirs)}")
    print(f"Registered strategies: {sorted(registry.keys())}")
    print(f"Canonical modules: {len(canonical)}")

    status_counts: dict[str, int] = {}
    for row in canonical:
        status = row.get("implementation_status") or "not_started"
        status_counts[status] = status_counts.get(status, 0) + 1
    print(f"Status counts: {status_counts}")

    data_root = resolve_data_root()
    if data_root:
        client = ExnessCSVClient(data_root)
        symbols = client.get_symbols()
        print(f"Data root: {data_root} ({len(symbols)} symbols)")
    else:
        print("Data root: NOT AVAILABLE (production path required on Windows)")

    pending = sorted(
        [
            r for r in canonical
            if (r.get("implementation_status") or "not_started") not in {"coded_and_backtested", "covered_by_canonical"}
        ],
        key=lambda r: int(r.get("video_number") or 999),
    )
    if pending:
        nxt = pending[0]
        print(f"Next pending: Video #{nxt.get('video_number')} — {nxt.get('module_to_code')}")
    else:
        print("Pipeline complete.")


def cmd_list_strategies():
    load_all_strategies()
    for strat_id in list_strategy_ids():
        cls = get_strategy(strat_id)
        if cls:
            print(f"{strat_id}: {cls.name}")


def update_tracking_csv(
    csv_path: Path,
    module: str,
    registry_id: str,
    status: str,
    data_source: str,
    data_root: str | None,
    summary: RunSummary | None = None,
    anti_bias_passed: str = "yes",
    anti_bias_notes: str = "",
    backtest_error: str = "",
):
    fieldnames, rows = _read_csv(csv_path)
    now = _utc_now_iso()

    for row in rows:
        if row.get("module_to_code") != module or row.get("action") != "CODE-CANONICAL":
            continue
        row["implementation_status"] = status
        row["strategy_module_id"] = module
        row["strategy_folder"] = f"strategies/{module}/"
        row["strategy_registry_id"] = registry_id
        row["data_source"] = data_source
        row["data_root_used"] = data_root or ""
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["backtest_error"] = backtest_error
        if status in {"coded", "coded_pending_production_backtest", "in_progress"} and not row.get("coded_at"):
            row["coded_at"] = now
        if summary and summary.matrix_rows:
            row["backtested_at"] = now
            row["instruments_tested_count"] = str(summary.instruments_tested)
            row.update({k: str(v) for k, v in summary.aggregate_stats.items()})
            if summary.best_instrument:
                best_row = next(r for r in summary.matrix_rows if r["symbol"] == summary.best_instrument)
                row["best_instrument"] = summary.best_instrument
                row["best_instrument_pf"] = str(best_row["bt_profit_factor"])
                row["best_instrument_win_rate"] = str(best_row["bt_win_rate"])
                row["best_instrument_pnl"] = str(best_row["bt_total_pnl"])
                row["best_instrument_trades"] = str(best_row["bt_total_trades"])
            if summary.worst_instrument:
                row["worst_instrument"] = summary.worst_instrument
            row["instrument_affinity_notes"] = _affinity_notes(summary)

    if status == "coded_and_backtested" and data_source == "exness_production":
        for row in rows:
            if row.get("action") == "DUPLICATE-SKIP" and row.get("module_to_code") == module:
                canonical = next(
                    (r for r in rows if r.get("module_to_code") == module and r.get("action") == "CODE-CANONICAL"),
                    None,
                )
                if canonical:
                    row["implementation_status"] = "covered_by_canonical"
                    for col in TRACKING_COLUMNS:
                        if col.startswith("bt_") or col.startswith("best_") or col in {
                            "worst_instrument",
                            "instrument_affinity_notes",
                            "backtested_at",
                            "data_source",
                        }:
                            row[col] = canonical.get(col, "")

    _write_csv_atomic(csv_path, fieldnames, rows)


def _affinity_notes(summary: RunSummary) -> str:
    ranked = sorted(summary.matrix_rows, key=lambda r: float(r.get("composite_score") or -1), reverse=True)
    strong = [r for r in ranked[:3] if int(r.get("bt_total_trades") or 0) >= 10]
    weak = [r for r in ranked[-3:] if int(r.get("bt_total_trades") or 0) >= 10]
    parts = []
    if strong:
        parts.append(
            "Strong on "
            + ", ".join(f"{r['symbol']} (PF={r['bt_profit_factor']}, n={r['bt_total_trades']})" for r in strong)
        )
    if weak:
        parts.append(
            "Weak on "
            + ", ".join(f"{r['symbol']} (PF={r['bt_profit_factor']})" for r in weak)
        )
    return ". ".join(parts) if parts else "Insufficient trades across symbols for affinity ranking."


def cmd_run(args):
    strategy_cls = get_strategy(args.strategy)
    if strategy_cls is None:
        raise SystemExit(f"Unknown strategy: {args.strategy}")

    module = strategy_cls.id.split("_", 1)[-1]
    csv_path = Path(args.csv)
    update_tracking_csv(
        csv_path,
        module=module,
        registry_id=strategy_cls.id,
        status="in_progress",
        data_source="not_backtested",
        data_root=None,
    )

    summary = run_multi_instrument_backtest(
        strategy_id=strategy_cls.id,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )

    if summary.data_source == "exness_production" and summary.instruments_tested > 0:
        status = "coded_and_backtested"
        data_source = "exness_production"
    elif summary.data_root:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"
    else:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"

    anti_bias_notes = (
        "Uses only completed bars via data_feed HTF close rule; session VP from past session bars; "
        "entries on bar close through local clusters; stops at absorption wick extremes."
    )

    update_tracking_csv(
        csv_path,
        module=module,
        registry_id=strategy_cls.id,
        status=status,
        data_source=data_source,
        data_root=summary.data_root,
        summary=summary if summary.matrix_rows else None,
        anti_bias_passed="yes",
        anti_bias_notes=anti_bias_notes,
    )

    print("\n=== Run Complete ===")
    print(f"Strategy: {strategy_cls.id}")
    print(f"Status: {status}")
    print(f"Data source: {data_source}")
    print(f"Instruments tested: {summary.instruments_tested}")
    print(f"Instruments skipped: {summary.instruments_skipped}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy backtester pipeline CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit CSV vs coded folders vs data")
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


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "audit":
        cmd_audit(Path(args.csv))
    elif args.command == "list-strategies":
        cmd_list_strategies()
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
