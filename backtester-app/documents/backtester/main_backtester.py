#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, run.
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
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
DEFAULT_DATA_ROOT = Path(
    r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
)
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

if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class InstrumentResult:
    symbol: str
    stats: dict[str, Any]
    composite_score: float = 0.0
    rank_within_strategy: int = 0
    data_quality_note: str = ""
    result_path: str = ""


@dataclass
class MultiBacktestSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    instrument_results: list[InstrumentResult] = field(default_factory=list)
    best_instrument: Optional[str] = None
    worst_instrument: Optional[str] = None
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_root: str | None = None) -> tuple[Path | None, str]:
    if cli_root:
        path = Path(cli_root)
        if path.is_dir() and _has_symbol_folders(path):
            return path, "cli"
    env_path = os.environ.get("LOCAL_HISTORY_PATH", "")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_folders(path):
            return path, "env"
    if DEFAULT_DATA_ROOT.is_dir() and _has_symbol_folders(DEFAULT_DATA_ROOT):
        return DEFAULT_DATA_ROOT, "default"
    return None, "none"


def _has_symbol_folders(path: Path) -> bool:
    return any(p.is_dir() and not p.name.startswith(".") for p in path.iterdir())


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        delete=False,
        dir=csv_path.parent,
    ) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        tmp_path = Path(tmp.name)
    tmp_path.replace(csv_path)


def ensure_tracking_columns(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    fieldnames, rows = _read_csv_rows(csv_path)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def load_strategy_config(module_name: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def composite_score(
    stats: dict[str, Any],
    best_pnl: float,
    min_trades: int = 10,
) -> float:
    trades = int(stats.get("total_trades", 0))
    if trades < min_trades:
        return 0.0
    pf = min(float(stats.get("profit_factor", 0) or 0), 5.0) / 5.0 * 0.35
    wr = float(stats.get("win_rate", 0) or 0) / 100.0 * 0.20
    sharpe = float(stats.get("sharpe_ratio", 0) or 0)
    sharpe_norm = min(max(sharpe, -2), 3) / 3.0 * 0.20
    pnl = float(stats.get("total_pnl", 0) or 0)
    pnl_norm = (pnl / best_pnl) * 0.15 if best_pnl > 0 else 0.0
    trade_norm = min(trades, 50) / 50.0 * 0.10
    return round(pf + wr + sharpe_norm + pnl_norm + trade_norm, 4)


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    config_defaults: dict[str, Any],
    quiet: bool = True,
) -> tuple[Optional[dict[str, Any]], str]:
    required_tfs = [tf_from_string(tf) for tf in config_defaults.get("required_timeframes", ["M1"])]
    ok, missing = client.has_required_timeframes(symbol, required_tfs)
    if not ok:
        return None, f"missing timeframes: {', '.join(missing)}"

    start, end = client.get_full_date_range(symbol, required_tfs)
    if start is None or end is None:
        return None, "no date range"

    bt_defaults = config_defaults.get("backtest_defaults", {})
    config = BacktestConfig(
        strategy_id=strategy_cls.id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=float(bt_defaults.get("initial_balance", 10000.0)),
        risk_per_trade=float(bt_defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(bt_defaults.get("spread_pips", 1.0)),
        slippage_pips=float(bt_defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(bt_defaults.get("commission_per_lot", 7.0)),
    )

    strategy = strategy_cls()
    engine = BacktestEngine(config, strategy, client, quiet=quiet)
    result = engine.run()
    result_dict = result.to_dict()

    result_dir = output_dir / strategy_cls.id
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{symbol}.json"
    with result_path.open("w", encoding="utf-8") as handle:
        json.dump(result_dict, handle, indent=2)

    stats = result_dict["stats"]
    stats["total_pnl"] = sum(
        t.get("pnl", 0) for t in result_dict.get("trades", [])
    )
    return stats, ""


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    quiet: bool = True,
) -> MultiBacktestSummary:
    load_all_strategies()
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    module_name = strategy_cls.id.split("_", 1)[-1] if "_" in strategy_cls.id else strategy_cls.id
    config_data = load_strategy_config(module_name)
    video_number = str(config_data.get("video_number", ""))

    output_path = Path(output_dir) if output_dir else DEFAULT_OUTPUT
    output_path.mkdir(parents=True, exist_ok=True)

    resolved_root, _ = resolve_data_root(str(data_root) if data_root else None)
    summary = MultiBacktestSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module_name,
        video_number=video_number,
    )

    if resolved_root is None:
        summary.data_source = "not_backtested"
        return summary

    summary.data_root_used = str(resolved_root)
    summary.data_source = "exness_production"
    client = ExnessCSVClient(resolved_root)

    if symbols == "all":
        symbol_list = client.get_symbols()
    elif isinstance(symbols, str):
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        symbol_list = list(symbols)

    summary.instruments_scanned = len(symbol_list)
    min_trades = int(config_data.get("min_trades_for_ranking", 10))
    raw_results: list[InstrumentResult] = []

    for symbol in symbol_list:
        stats, note = run_single_symbol_backtest(
            strategy_cls,
            symbol,
            client,
            output_path,
            config_data,
            quiet=quiet,
        )
        if stats is None:
            summary.instruments_skipped += 1
            raw_results.append(
                InstrumentResult(symbol=symbol, stats={}, data_quality_note=note)
            )
            continue

        summary.instruments_tested += 1
        result_path = str(output_path / strategy_cls.id / f"{symbol}.json")
        raw_results.append(
            InstrumentResult(
                symbol=symbol,
                stats=stats,
                result_path=result_path,
            )
        )

    best_pnl = max(
        (float(r.stats.get("total_pnl", 0) or 0) for r in raw_results if r.stats),
        default=0.0,
    )
    if best_pnl <= 0:
        best_pnl = max(
            (abs(float(r.stats.get("total_pnl", 0) or 0)) for r in raw_results if r.stats),
            default=1.0,
        )

    for item in raw_results:
        if item.stats:
            item.composite_score = composite_score(item.stats, best_pnl, min_trades)

    ranked = sorted(
        [r for r in raw_results if r.stats],
        key=lambda r: r.composite_score,
        reverse=True,
    )
    for idx, item in enumerate(ranked, start=1):
        item.rank_within_strategy = idx

    rankable = [r for r in ranked if int(r.stats.get("total_trades", 0)) >= min_trades]
    if rankable:
        summary.best_instrument = rankable[0].symbol
        summary.worst_instrument = rankable[-1].symbol

    summary.instrument_results = raw_results
    summary.aggregate_stats = _aggregate_stats([r.stats for r in raw_results if r.stats])
    summary.matrix_rows = _build_matrix_rows(summary, raw_results, min_trades)
    return summary


def _aggregate_stats(stats_list: list[dict[str, Any]]) -> dict[str, Any]:
    if not stats_list:
        return {}
    total_trades = sum(int(s.get("total_trades", 0)) for s in stats_list)
    total_winners = sum(int(s.get("winning_trades", 0)) for s in stats_list)
    total_pnl = sum(float(s.get("total_pnl", 0) or 0) for s in stats_list)
    gross_profit = sum(
        float(s.get("total_pnl", 0) or 0)
        for s in stats_list
        if float(s.get("total_pnl", 0) or 0) > 0
    )
    gross_loss = abs(
        sum(
            float(s.get("total_pnl", 0) or 0)
            for s in stats_list
            if float(s.get("total_pnl", 0) or 0) < 0
        )
    )
    return {
        "total_trades": total_trades,
        "win_rate": round(total_winners / total_trades * 100, 2) if total_trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0,
        "max_drawdown_pct": max(float(s.get("max_drawdown_pct", 0) or 0) for s in stats_list),
        "total_pnl": round(total_pnl, 2),
        "sharpe_ratio": round(
            sum(float(s.get("sharpe_ratio", 0) or 0) for s in stats_list) / len(stats_list),
            2,
        ),
        "avg_rr": round(
            sum(float(s.get("avg_rr", 0) or 0) for s in stats_list) / len(stats_list),
            2,
        ),
    }


def _build_matrix_rows(
    summary: MultiBacktestSummary,
    results: list[InstrumentResult],
    min_trades: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now = _utc_now_iso()
    for item in results:
        if not item.stats:
            rows.append(
                {
                    "strategy_registry_id": summary.strategy_id,
                    "strategy_module_id": summary.strategy_module_id,
                    "video_number": summary.video_number,
                    "symbol": item.symbol,
                    "data_quality_note": item.data_quality_note,
                    "data_source": summary.data_source,
                    "backtested_at": now,
                }
            )
            continue
        rows.append(
            {
                "strategy_registry_id": summary.strategy_id,
                "strategy_module_id": summary.strategy_module_id,
                "video_number": summary.video_number,
                "symbol": item.symbol,
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
                "composite_score": item.composite_score,
                "rank_within_strategy": item.rank_within_strategy,
                "backtest_result_json": item.result_path,
                "backtested_at": now,
                "data_quality_note": item.data_quality_note,
                "data_source": summary.data_source,
            }
        )
    return rows


def update_matrix_csv(matrix_rows: list[dict[str, Any]]):
    MATRIX_CSV.parent.mkdir(parents=True, exist_ok=True)
    if MATRIX_CSV.exists():
        fieldnames, existing = _read_csv_rows(MATRIX_CSV)
    else:
        fieldnames = list(MATRIX_COLUMNS)
        existing = []

    for col in MATRIX_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    index: dict[tuple[str, str], dict[str, str]] = {}
    for row in existing:
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        index[key] = row

    for row in matrix_rows:
        key = (str(row.get("strategy_registry_id", "")), str(row.get("symbol", "")))
        merged = index.get(key, {})
        merged.update({k: str(v) for k, v in row.items() if v is not None})
        index[key] = merged

    _write_csv_atomic(MATRIX_CSV, fieldnames, list(index.values()))


def update_strategy_csv(
    csv_path: Path,
    module_name: str,
    summary: MultiBacktestSummary,
    anti_bias_passed: str,
    anti_bias_notes: str,
    implementation_status: str,
):
    fieldnames, rows = ensure_tracking_columns(csv_path)
    now = _utc_now_iso()
    agg = summary.aggregate_stats
    best_stats = next(
        (r for r in summary.instrument_results if r.symbol == summary.best_instrument),
        None,
    )

    for row in rows:
        if row.get("module_to_code") != module_name or row.get("action") != "CODE-CANONICAL":
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
        if implementation_status in {"coded_and_backtested", "coded_pending_production_backtest"}:
            if not row.get("coded_at"):
                row["coded_at"] = now
        if summary.data_source == "exness_production" and summary.instruments_tested > 0:
            row["backtested_at"] = now
        if agg:
            row["bt_total_trades_all"] = str(agg.get("total_trades", ""))
            row["bt_win_rate_all"] = str(agg.get("win_rate", ""))
            row["bt_profit_factor_all"] = str(agg.get("profit_factor", ""))
            row["bt_max_drawdown_pct_all"] = str(agg.get("max_drawdown_pct", ""))
            row["bt_total_pnl_all"] = str(agg.get("total_pnl", ""))
            row["bt_sharpe_ratio_all"] = str(agg.get("sharpe_ratio", ""))
            row["bt_avg_rr_all"] = str(agg.get("avg_rr", ""))
        if summary.best_instrument and best_stats:
            row["best_instrument"] = summary.best_instrument
            row["best_instrument_pf"] = str(best_stats.stats.get("profit_factor", ""))
            row["best_instrument_win_rate"] = str(best_stats.stats.get("win_rate", ""))
            row["best_instrument_pnl"] = str(best_stats.stats.get("total_pnl", ""))
            row["best_instrument_trades"] = str(best_stats.stats.get("total_trades", ""))
        if summary.worst_instrument:
            row["worst_instrument"] = summary.worst_instrument
        row["instrument_affinity_notes"] = _affinity_notes(summary)

    if implementation_status == "coded_and_backtested" and summary.data_source == "exness_production":
        canonical_row = next(
            (r for r in rows if r.get("module_to_code") == module_name),
            None,
        )
        if canonical_row:
            for row in rows:
                if row.get("action") != "DUPLICATE-SKIP":
                    continue
                if row.get("module_to_code") != module_name:
                    continue
                row["implementation_status"] = "covered_by_canonical"
                for col in TRACKING_COLUMNS:
                    if col in canonical_row and col not in {"implementation_status"}:
                        row[col] = canonical_row.get(col, "")

    _write_csv_atomic(csv_path, fieldnames, rows)


def _affinity_notes(summary: MultiBacktestSummary) -> str:
    ranked = sorted(
        [r for r in summary.instrument_results if r.stats],
        key=lambda r: r.composite_score,
        reverse=True,
    )
    if not ranked:
        return "No instruments backtested — production data unavailable in this environment."
    top = ranked[:2]
    bottom = ranked[-2:]
    top_txt = ", ".join(
        f"{r.symbol} (PF={r.stats.get('profit_factor')}, trades={r.stats.get('total_trades')})"
        for r in top
        if r.stats
    )
    bot_txt = ", ".join(
        f"{r.symbol} (PF={r.stats.get('profit_factor')})" for r in bottom if r.stats
    )
    return f"Stronger on {top_txt}. Weaker on {bot_txt}."


def cmd_audit(csv_path: Path):
    fieldnames, rows = ensure_tracking_columns(csv_path)
    coded_dirs = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"tests", "__pycache__"}
    }
    load_all_strategies()
    registered = {cls.id: cls for cls in get_all_strategies()}

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(
        1 for r in canonical if r.get("implementation_status") == "coded_and_backtested"
    )

    data_root, source = resolve_data_root()
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_root else 0

    print("=== Backtester Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Canonical modules: {len(canonical)} | coded_and_backtested: {done}")
    print(f"Strategy folders on disk: {sorted(coded_dirs)}")
    print(f"Registered strategies: {list(registered.keys())}")
    print(f"main_backtester.py: {'yes' if Path(__file__).exists() else 'no'}")
    print(f"Data root ({source}): {data_root or 'UNAVAILABLE'} | symbols: {symbol_count}")

    pending = [
        r for r in canonical
        if r.get("implementation_status", "") in {"", "not_started", "in_progress", "failed"}
    ]
    if pending:
        pending.sort(key=lambda r: int(r.get("video_number", 999)))
        nxt = pending[0]
        print(
            f"Next pending: Video #{nxt.get('video_number')} — "
            f"{nxt.get('title')} ({nxt.get('module_to_code')})"
        )
    elif done == len(canonical):
        print("Pipeline complete.")


def cmd_list_strategies():
    load_all_strategies()
    for cls in get_all_strategies():
        print(f"{cls.id:40} {cls.name}")


def cmd_run(args: argparse.Namespace):
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
        quiet=not args.verbose,
    )

    if summary.matrix_rows:
        update_matrix_csv(summary.matrix_rows)

    module_name = summary.strategy_module_id
    if summary.data_source == "exness_production" and summary.instruments_tested > 0:
        status = "coded_and_backtested"
    elif summary.data_source == "not_backtested":
        status = "coded_pending_production_backtest"
    else:
        status = "coded"

    anti_bias = "yes"
    anti_notes = (
        "M1 signals use closed bars only; session VP from past session bars; "
        "HTF feed enforces bar-close visibility; entries on M1 close; "
        "SL/TP from structure not optimized on results."
    )

    update_strategy_csv(
        Path(args.csv),
        module_name,
        summary,
        anti_bias,
        anti_notes,
        status if summary.instruments_tested else "coded_pending_production_backtest",
    )

    print(json.dumps(
        {
            "strategy_id": summary.strategy_id,
            "instruments_tested": summary.instruments_tested,
            "instruments_skipped": summary.instruments_skipped,
            "best_instrument": summary.best_instrument,
            "aggregate": summary.aggregate_stats,
            "data_source": summary.data_source,
        },
        indent=2,
    ))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit CSV vs disk vs registry")
    audit_p.add_argument("--csv", default=str(DEFAULT_CSV))

    sub.add_parser("list-strategies", help="List registered strategies")

    run_p = sub.add_parser("run", help="Run multi-instrument backtest")
    run_p.add_argument("--strategy", required=True)
    run_p.add_argument("--symbols", default="all")
    run_p.add_argument("--data-root", default=None)
    run_p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_p.add_argument("--csv", default=str(DEFAULT_CSV))
    run_p.add_argument("--verbose", action="store_true")
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
