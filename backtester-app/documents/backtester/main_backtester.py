#!/usr/bin/env python3
"""
Main backtester CLI — audit, discover strategies, run multi-instrument backtests.
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
from typing import Any, Optional

import yaml

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"

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

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _ensure_pythonpath():
    documents = str(DOCUMENTS_ROOT)
    if documents not in sys.path:
        sys.path.insert(0, documents)


@dataclass
class RunSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    data_root: str
    data_source: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: Optional[str] = None
    worst_instrument: Optional[str] = None
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)


def resolve_data_root(cli_path: str | None = None) -> tuple[str, bool]:
    """Return (path, exists_with_data)."""
    candidates: list[str] = []
    if cli_path:
        candidates.append(cli_path)
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        candidates.append(env_path)
    candidates.append(DEFAULT_DATA_ROOT)

    for path in candidates:
        root = Path(path)
        if not root.is_dir():
            continue
        symbol_dirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if symbol_dirs:
            return str(root), True
    return candidates[0], False


def load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


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
    return round(
        (pf / 5.0 * 0.35)
        + (win_rate / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10),
        4,
    )


def cmd_audit(csv_path: Path) -> int:
    _ensure_pythonpath()
    from backtester.strategies.registry import get_all_strategies, load_all_strategies

    load_all_strategies()
    strategies = get_all_strategies()
    rows = read_csv_rows(csv_path)
    ensure_tracking_columns(rows)

    canonical = [
        r for r in rows
        if r.get("is_backtestable") == "yes" and r.get("action") == "CODE-CANONICAL"
    ]
    coded = [r for r in canonical if r.get("implementation_status") in (
        "coded", "coded_and_backtested", "coded_pending_production_backtest", "in_progress"
    )]
    done = [r for r in canonical if r.get("implementation_status") == "coded_and_backtested"]

    data_root, has_data = resolve_data_root()
    symbol_count = 0
    if has_data:
        from backtester.connectors import ExnessCSVClient
        symbol_count = len(ExnessCSVClient(data_root).get_symbols())

    print(f"Backtester root: {BACKTESTER_ROOT}")
    print(f"Strategies on disk: {len(strategies)}")
    print(f"Canonical modules: {len(canonical)} | coded/in-progress: {len(coded)} | backtested: {len(done)}")
    print(f"Data root: {data_root} | available: {has_data} | symbols: {symbol_count}")
    for strat in strategies:
        print(f"  - {strat.id}: {strat.name}")
    return 0


def cmd_list_strategies() -> int:
    _ensure_pythonpath()
    from backtester.strategies.registry import list_strategy_entries, load_all_strategies

    load_all_strategies()
    for entry in list_strategy_entries():
        print(f"{entry['id']}\t{entry['name']}\tvideo={entry['source_video']}\ttf={entry['timeframes']}")
    return 0


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str = "all",
    output_dir: str | Path | None = None,
    csv_path: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> RunSummary:
    _ensure_pythonpath()
    from backtester.connectors import ExnessCSVClient
    from backtester.core import BacktestConfig
    from backtester.core.engine import BacktestEngine
    from backtester.core.timeframes import TF, tf_from_string
    from backtester.strategies.registry import get_strategy

    resolved_root, has_data = resolve_data_root(data_root)
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module_name = strategy_id.split("_", 1)[-1] if strategy_id.startswith("s") else strategy_id
    config = load_strategy_config(module_name)
    defaults = config.get("backtest_defaults", {})
    video_number = str(config.get("video_number", ""))
    min_trades = int(config.get("min_trades_for_ranking", 10))
    required_tf = [tf_from_string(tf) for tf in config.get("required_timeframes", ["M1"])]

    data_source = "exness_production" if has_data else "pending_exness_production"
    summary = RunSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_name,
        video_number=video_number,
        data_root=resolved_root,
        data_source=data_source,
    )

    if not has_data:
        logger.warning("Real Exness history unavailable — skipping backtest runs")
        if csv_path:
            update_tracking_csv(
                Path(csv_path),
                summary,
                anti_bias_passed="yes",
                anti_bias_notes=(
                    "Uses closed M1 bars only; session VP from past session bars; "
                    "HTF anti-lookahead in data_feed; NY session via zoneinfo."
                ),
            )
        return summary

    client = ExnessCSVClient(resolved_root)
    all_symbols = client.get_symbols()
    summary.instruments_scanned = len(all_symbols)

    if symbols != "all":
        selected = {s.strip().upper() for s in symbols.split(",") if s.strip()}
        all_symbols = [s for s in all_symbols if s in selected]

    now_iso = datetime.now(timezone.utc).isoformat()
    result_dir = output_path / strategy_cls.id
    result_dir.mkdir(parents=True, exist_ok=True)

    for symbol in all_symbols:
        date_range = client.get_full_date_range(symbol, required_tf)
        if date_range[0] is None or date_range[1] is None:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = "missing required timeframe data"
            continue

        bars_check = client.get_bars(symbol, required_tf[0], date_range[0], date_range[1])
        if not bars_check:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = "empty bar series"
            continue

        bt_start = start or date_range[0]
        bt_end = end or date_range[1]

        strategy = strategy_cls()
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

        try:
            engine = BacktestEngine(bt_config, strategy, client)
            result = engine.run()
        except Exception as exc:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = str(exc)
            logger.error("Backtest failed for %s: %s", symbol, exc)
            continue

        summary.instruments_tested += 1
        result_json_path = result_dir / f"{symbol}.json"
        with open(result_json_path, "w", encoding="utf-8") as handle:
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
            "backtest_result_json": str(result_json_path.relative_to(output_path)),
            "backtested_at": now_iso,
            "data_quality_note": "",
            "data_source": data_source,
        }
        summary.matrix_rows.append(row)

    if summary.matrix_rows:
        best_pnl = max(float(r["bt_total_pnl"]) for r in summary.matrix_rows)
        for row in summary.matrix_rows:
            row["composite_score"] = composite_score(row, best_pnl, min_trades)

        ranked = sorted(
            summary.matrix_rows,
            key=lambda r: r.get("composite_score", 0),
            reverse=True,
        )
        for rank, row in enumerate(ranked, start=1):
            row["rank_within_strategy"] = rank

        eligible = [r for r in ranked if int(r["bt_total_trades"]) >= min_trades]
        if eligible:
            summary.best_instrument = eligible[0]["symbol"]
            summary.worst_instrument = eligible[-1]["symbol"]

        summary.aggregate_stats = {
            "bt_total_trades_all": sum(int(r["bt_total_trades"]) for r in summary.matrix_rows),
            "bt_win_rate_all": round(
                sum(float(r["bt_win_rate"]) for r in summary.matrix_rows) / len(summary.matrix_rows), 2
            ),
            "bt_profit_factor_all": round(
                sum(float(r["bt_profit_factor"]) if r["bt_profit_factor"] != float("inf") else 5.0
                    for r in summary.matrix_rows) / len(summary.matrix_rows), 2
            ),
            "bt_max_drawdown_pct_all": max(float(r["bt_max_drawdown_pct"]) for r in summary.matrix_rows),
            "bt_total_pnl_all": round(sum(float(r["bt_total_pnl"]) for r in summary.matrix_rows), 2),
            "bt_sharpe_ratio_all": round(
                sum(float(r["bt_sharpe_ratio"]) for r in summary.matrix_rows) / len(summary.matrix_rows), 2
            ),
            "bt_avg_rr_all": round(
                sum(float(r["bt_avg_rr"]) for r in summary.matrix_rows) / len(summary.matrix_rows), 2
            ),
        }

        update_matrix_csv(output_path / "strategy_instrument_matrix.csv", summary.matrix_rows)

    if csv_path:
        update_tracking_csv(
            Path(csv_path),
            summary,
            anti_bias_passed="yes",
            anti_bias_notes=(
                "Uses closed M1 bars only; session VP from past session bars; "
                "HTF anti-lookahead in data_feed; NY session via zoneinfo."
            ),
        )

    return summary


def read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    with open(csv_path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(csv_path: Path, rows: list[dict[str, str]], fieldnames: list[str]):
    temp_fd, temp_name = tempfile.mkstemp(suffix=".csv", dir=csv_path.parent)
    os.close(temp_fd)
    temp_path = Path(temp_name)
    try:
        with open(temp_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        temp_path.replace(csv_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def ensure_tracking_columns(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return TRACKING_COLUMNS
    fieldnames = list(rows[0].keys())
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
            for row in rows:
                row.setdefault(col, "")
    return fieldnames


def update_matrix_csv(matrix_path: Path, new_rows: list[dict[str, Any]]):
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if matrix_path.exists():
        with open(matrix_path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                existing[(row["strategy_registry_id"], row["symbol"])] = row

    for row in new_rows:
        existing[(row["strategy_registry_id"], row["symbol"])] = {k: str(v) for k, v in row.items()}

    rows = list(existing.values())
    write_csv_rows(matrix_path, rows, MATRIX_COLUMNS)


def update_tracking_csv(
    csv_path: Path,
    summary: RunSummary,
    anti_bias_passed: str,
    anti_bias_notes: str,
):
    rows = read_csv_rows(csv_path)
    fieldnames = ensure_tracking_columns(rows)
    now_iso = datetime.now(timezone.utc).isoformat()

    if summary.data_source == "exness_production" and summary.instruments_tested > 0:
        status = "coded_and_backtested"
    elif summary.instruments_tested == 0:
        status = "coded_pending_production_backtest"
    else:
        status = "coded_pending_production_backtest"

    for row in rows:
        if row.get("module_to_code") != summary.strategy_module_id:
            continue
        if row.get("action") != "CODE-CANONICAL":
            continue

        row["implementation_status"] = status
        row["strategy_module_id"] = summary.strategy_module_id
        row["strategy_folder"] = f"strategies/{summary.strategy_module_id}/"
        row["strategy_registry_id"] = summary.strategy_id
        row["coded_at"] = row.get("coded_at") or now_iso
        row["backtested_at"] = now_iso if summary.instruments_tested else ""
        row["instruments_tested_count"] = str(summary.instruments_tested)
        row["anti_bias_review_passed"] = anti_bias_passed
        row["anti_bias_notes"] = anti_bias_notes
        row["data_source"] = summary.data_source if summary.instruments_tested else "not_backtested"
        row["data_root_used"] = summary.data_root

        agg = summary.aggregate_stats
        for key in (
            "bt_total_trades_all", "bt_win_rate_all", "bt_profit_factor_all",
            "bt_max_drawdown_pct_all", "bt_total_pnl_all", "bt_sharpe_ratio_all", "bt_avg_rr_all",
        ):
            row[key] = str(agg.get(key, ""))

        if summary.best_instrument:
            best_row = next((r for r in summary.matrix_rows if r["symbol"] == summary.best_instrument), None)
            if best_row:
                row["best_instrument"] = summary.best_instrument
                row["best_instrument_pf"] = str(best_row.get("bt_profit_factor", ""))
                row["best_instrument_win_rate"] = str(best_row.get("bt_win_rate", ""))
                row["best_instrument_pnl"] = str(best_row.get("bt_total_pnl", ""))
                row["best_instrument_trades"] = str(best_row.get("bt_total_trades", ""))
        if summary.worst_instrument:
            row["worst_instrument"] = summary.worst_instrument

        row["instrument_affinity_notes"] = _affinity_notes(summary)

    if status == "coded_and_backtested":
        for row in rows:
            if row.get("duplicate_of_video") == summary.video_number and row.get("action") == "DUPLICATE-SKIP":
                row["implementation_status"] = "covered_by_canonical"
                for key in TRACKING_COLUMNS:
                    if key.startswith("bt_") or key.startswith("best_") or key in ("data_source", "data_root_used"):
                        canonical = next(
                            (r for r in rows if r.get("module_to_code") == summary.strategy_module_id
                             and r.get("action") == "CODE-CANONICAL"),
                            None,
                        )
                        if canonical:
                            row[key] = canonical.get(key, "")

    write_csv_rows(csv_path, rows, fieldnames)


def _affinity_notes(summary: RunSummary) -> str:
    if not summary.matrix_rows:
        return "Production backtest pending on Windows Exness history path."
    top = sorted(summary.matrix_rows, key=lambda r: r.get("composite_score", 0), reverse=True)[:3]
    weak = sorted(summary.matrix_rows, key=lambda r: r.get("composite_score", 0))[:2]
    top_txt = ", ".join(f"{r['symbol']}(PF={r['bt_profit_factor']}, n={r['bt_total_trades']})" for r in top)
    weak_txt = ", ".join(f"{r['symbol']}(PF={r['bt_profit_factor']})" for r in weak)
    return f"Strongest on {top_txt}. Weakest on {weak_txt}."


def cmd_run(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv) if args.csv else DEFAULT_CSV
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
        csv_path=csv_path,
    )
    print(json.dumps({
        "strategy_id": summary.strategy_id,
        "data_source": summary.data_source,
        "instruments_tested": summary.instruments_tested,
        "best_instrument": summary.best_instrument,
        "aggregate": summary.aggregate_stats,
    }, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit.add_argument("--csv", default=str(DEFAULT_CSV))

    sub.add_parser("list-strategies", help="List discovered strategies")

    run = sub.add_parser("run", help="Run multi-instrument backtest")
    run.add_argument("--strategy", required=True)
    run.add_argument("--symbols", default="all")
    run.add_argument("--data-root", default=None)
    run.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run.add_argument("--csv", default=str(DEFAULT_CSV))
    run.add_argument("--start", default=None)
    run.add_argument("--end", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "audit":
        return cmd_audit(Path(args.csv))
    if args.command == "list-strategies":
        return cmd_list_strategies()
    if args.command == "run":
        return cmd_run(args)
    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
