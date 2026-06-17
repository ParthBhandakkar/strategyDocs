#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, and multi-instrument run.
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
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_strategy, list_strategy_ids, load_all_strategies

logger = logging.getLogger(__name__)

DEFAULT_WINDOWS_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"
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


@dataclass
class InstrumentResult:
    symbol: str
    stats: dict[str, Any]
    composite_score: float = 0.0
    rank: int = 0
    start_date: str = ""
    end_date: str = ""
    data_quality_note: str = ""
    json_path: str = ""


@dataclass
class MultiBacktestSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    instrument_results: list[InstrumentResult] = field(default_factory=list)
    best_instrument: str = ""
    worst_instrument: str = ""
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_root: str | None = None) -> Path | None:
    if cli_root:
        path = Path(cli_root)
        if path.is_dir() and _has_symbol_data(path):
            return path
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_data(path):
            return path
    default = Path(DEFAULT_WINDOWS_DATA_ROOT)
    if default.is_dir() and _has_symbol_data(default):
        return default
    return None


def _has_symbol_data(root: Path) -> bool:
    for child in root.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            for tf_dir in child.iterdir():
                if tf_dir.is_dir() and list(tf_dir.glob("*.csv")):
                    return True
    return False


def load_strategy_config(module: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def compute_composite_score(stats: dict[str, Any], best_pnl: float) -> float:
    pf = min(float(stats.get("profit_factor", 0) or 0), 5.0) / 5.0 * 0.35
    wr = float(stats.get("win_rate", 0) or 0) / 100.0 * 0.20
    sharpe = float(stats.get("sharpe_ratio", 0) or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0 * 0.20
    pnl = float(stats.get("total_pnl", 0) or 0)
    pnl_norm = (pnl / best_pnl * 0.15) if best_pnl > 0 else 0.0
    trades = min(int(stats.get("total_trades", 0) or 0), 50) / 50.0 * 0.10
    return round(pf + wr + sharpe_norm + pnl_norm + trades, 4)


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    config_overrides: dict[str, Any],
    required_tfs: list[TF],
) -> InstrumentResult | None:
    start, end = client.get_full_date_range(symbol, required_tfs)
    if not start or not end:
        return InstrumentResult(
            symbol=symbol,
            stats={},
            data_quality_note="missing required timeframe data",
        )

    cfg = BacktestConfig(
        strategy_id=strategy_cls.id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=float(config_overrides.get("initial_balance", 10000.0)),
        risk_per_trade=float(config_overrides.get("risk_per_trade", 0.01)),
        spread_pips=float(config_overrides.get("spread_pips", 1.0)),
        slippage_pips=float(config_overrides.get("slippage_pips", 0.5)),
        commission_per_lot=float(config_overrides.get("commission_per_lot", 7.0)),
    )

    strategy = strategy_cls()
    engine = BacktestEngine(cfg, strategy, client)
    result = engine.run()

    result_dict = result.to_dict()
    stats = result_dict["stats"]
    strat_dir = output_dir / strategy_cls.id
    strat_dir.mkdir(parents=True, exist_ok=True)
    json_path = strat_dir / f"{symbol}.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(result_dict, handle, indent=2)

    return InstrumentResult(
        symbol=symbol,
        stats=stats,
        start_date=start.date().isoformat(),
        end_date=end.date().isoformat(),
        json_path=str(json_path),
    )


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | Path | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
) -> MultiBacktestSummary:
    load_all_strategies()
    strategy_cls = get_strategy(strategy_id)
    if not strategy_cls:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module = strategy_cls.__module__.split(".")[-1]
    yaml_cfg = load_strategy_config(module)
    bt_defaults = yaml_cfg.get("backtest_defaults", {})
    required_tf_names = yaml_cfg.get("required_timeframes", [])
    if not required_tf_names:
        required_tf_names = [tf.name for tf in strategy_cls.timeframes]
    required_tfs = [tf_from_string(name) for name in required_tf_names]
    min_trades = int(yaml_cfg.get("min_trades_for_ranking", 10))

    resolved_root = resolve_data_root(str(data_root) if data_root else None)
    summary = MultiBacktestSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=yaml_cfg.get("module", module),
        video_number=str(yaml_cfg.get("video_number", strategy_cls.source_video)),
        data_root_used=str(resolved_root) if resolved_root else "",
    )

    if not resolved_root:
        summary.data_source = "pending_exness_production"
        return summary

    client = ExnessCSVClient(resolved_root)
    all_symbols = client.get_symbols()
    summary.instruments_scanned = len(all_symbols)
    summary.data_source = "exness_production"

    if isinstance(symbols, str):
        if symbols.lower() == "all":
            target_symbols = all_symbols
        else:
            target_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        target_symbols = [s.upper() for s in symbols]

    out_path = Path(output_dir or DEFAULT_OUTPUT)
    out_path.mkdir(parents=True, exist_ok=True)

    results: list[InstrumentResult] = []
    for symbol in target_symbols:
        if symbol not in all_symbols:
            results.append(
                InstrumentResult(
                    symbol=symbol,
                    stats={},
                    data_quality_note="symbol folder not found under data root",
                )
            )
            summary.instruments_skipped += 1
            continue

        missing_tfs = []
        for tf in required_tfs:
            if not client.get_bars(symbol, tf):
                missing_tfs.append(tf.name)
        if missing_tfs:
            results.append(
                InstrumentResult(
                    symbol=symbol,
                    stats={},
                    data_quality_note=f"missing timeframes: {','.join(missing_tfs)}",
                )
            )
            summary.instruments_skipped += 1
            continue

        inst = run_single_symbol_backtest(
            strategy_cls, symbol, client, out_path, bt_defaults, required_tfs
        )
        if inst:
            results.append(inst)
            if inst.stats:
                summary.instruments_tested += 1
            else:
                summary.instruments_skipped += 1

    best_pnl = max(
        (float(r.stats.get("total_pnl", 0) or 0) for r in results if r.stats),
        default=0.0,
    )
    for inst in results:
        if inst.stats:
            inst.composite_score = compute_composite_score(inst.stats, best_pnl)

    ranked = sorted(
        [r for r in results if r.stats],
        key=lambda r: r.composite_score,
        reverse=True,
    )
    for idx, inst in enumerate(ranked, start=1):
        inst.rank = idx

    eligible = [r for r in ranked if int(r.stats.get("total_trades", 0) or 0) >= min_trades]
    if eligible:
        summary.best_instrument = eligible[0].symbol
        summary.worst_instrument = eligible[-1].symbol

    summary.instrument_results = results
    summary.matrix_rows = _build_matrix_rows(summary, results, min_trades)
    summary.aggregate_stats = _aggregate_stats(results)
    _write_matrix_csv(out_path / "strategy_instrument_matrix.csv", summary.matrix_rows)
    return summary


def _aggregate_stats(results: list[InstrumentResult]) -> dict[str, Any]:
    tested = [r for r in results if r.stats and int(r.stats.get("total_trades", 0) or 0) > 0]
    if not tested:
        return {}
    total_trades = sum(int(r.stats.get("total_trades", 0) or 0) for r in tested)
    total_wins = sum(int(r.stats.get("winning_trades", 0) or 0) for r in tested)
    total_pnl = sum(float(r.stats.get("total_pnl", 0) or 0) for r in tested)
    max_dd = max(float(r.stats.get("max_drawdown_pct", 0) or 0) for r in tested)
    pf_vals = [float(r.stats.get("profit_factor", 0) or 0) for r in tested if r.stats.get("profit_factor")]
    sharpe_vals = [float(r.stats.get("sharpe_ratio", 0) or 0) for r in tested]
    rr_vals = [float(r.stats.get("avg_rr", 0) or 0) for r in tested]
    gross_profit = sum(
        float(r.stats.get("total_pnl", 0) or 0)
        for r in tested
        if float(r.stats.get("total_pnl", 0) or 0) > 0
    )
    gross_loss = abs(
        sum(
            float(r.stats.get("total_pnl", 0) or 0)
            for r in tested
            if float(r.stats.get("total_pnl", 0) or 0) <= 0
        )
    )
    return {
        "total_trades": total_trades,
        "win_rate": round(total_wins / total_trades * 100, 2) if total_trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0,
        "max_drawdown_pct": round(max_dd, 2),
        "total_pnl": round(total_pnl, 2),
        "sharpe_ratio": round(sum(sharpe_vals) / len(sharpe_vals), 2) if sharpe_vals else 0.0,
        "avg_rr": round(sum(rr_vals) / len(rr_vals), 2) if rr_vals else 0.0,
    }


def _build_matrix_rows(
    summary: MultiBacktestSummary,
    results: list[InstrumentResult],
    min_trades: int,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for inst in results:
        stats = inst.stats or {}
        rows.append(
            {
                "strategy_registry_id": summary.strategy_id,
                "strategy_module_id": summary.strategy_module_id,
                "video_number": summary.video_number,
                "symbol": inst.symbol,
                "backtest_start_date": inst.start_date,
                "backtest_end_date": inst.end_date,
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
                "composite_score": inst.composite_score,
                "rank_within_strategy": inst.rank,
                "backtest_result_json": inst.json_path,
                "backtested_at": now if stats else "",
                "data_quality_note": inst.data_quality_note,
                "data_source": summary.data_source if stats else "not_backtested",
            }
        )
    return rows


def _write_matrix_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for row in rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = row

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda r: (r["strategy_registry_id"], r["symbol"])):
            writer.writerow(row)


def _atomic_csv_write(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", delete=False, dir=path.parent
    ) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _ensure_tracking_columns(fieldnames: list[str]) -> list[str]:
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames


def audit_csv(csv_path: Path) -> dict[str, Any]:
    load_all_strategies()
    coded_folders = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__"}
    }
    registered = set(list_strategy_ids())

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = _ensure_tracking_columns(list(reader.fieldnames or []))

    canonical = [
        r for r in rows if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    status_counts: dict[str, int] = {}
    for row in canonical:
        status = row.get("implementation_status") or "not_started"
        status_counts[status] = status_counts.get(status, 0) + 1

    data_root = resolve_data_root()
    symbol_count = len(ExnessCSVClient(data_root).get_symbols()) if data_root else 0

    return {
        "csv_path": str(csv_path),
        "canonical_total": len(canonical),
        "status_counts": status_counts,
        "coded_folders": sorted(coded_folders - {"base", "registry"}),
        "registered_strategies": sorted(registered),
        "data_root": str(data_root) if data_root else None,
        "symbol_count": symbol_count,
        "rows": rows,
        "fieldnames": fieldnames,
    }


def update_tracking_csv(
    csv_path: Path,
    video_number: str,
    updates: dict[str, str],
) -> None:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = _ensure_tracking_columns(list(reader.fieldnames or []))

    for row in rows:
        if row.get("video_number") == str(video_number) and row.get("action") == "CODE-CANONICAL":
            row.update(updates)

    _atomic_csv_write(csv_path, rows, fieldnames)


def cmd_audit(args: argparse.Namespace) -> int:
    info = audit_csv(Path(args.csv))
    print(f"CSV: {info['csv_path']}")
    print(f"Canonical modules: {info['canonical_total']}")
    print(f"Status counts: {info['status_counts']}")
    print(f"Strategy folders: {info['coded_folders']}")
    print(f"Registered IDs: {info['registered_strategies']}")
    print(f"Data root: {info['data_root'] or 'NOT AVAILABLE'}")
    print(f"Symbols under data root: {info['symbol_count']}")
    return 0


def cmd_list_strategies(_: argparse.Namespace) -> int:
    load_all_strategies()
    for strat_id in list_strategy_ids():
        cls = get_strategy(strat_id)
        print(f"{strat_id}\t{cls.name if cls else ''}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    print(json.dumps(
        {
            "strategy_id": summary.strategy_id,
            "instruments_scanned": summary.instruments_scanned,
            "instruments_tested": summary.instruments_tested,
            "instruments_skipped": summary.instruments_skipped,
            "best_instrument": summary.best_instrument,
            "worst_instrument": summary.worst_instrument,
            "aggregate_stats": summary.aggregate_stats,
            "data_source": summary.data_source,
            "data_root_used": summary.data_root_used,
        },
        indent=2,
    ))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit CSV vs coded folders vs data")
    audit_p.add_argument("--csv", default=str(DEFAULT_CSV))

    sub.add_parser("list-strategies", help="List registered strategy IDs")

    run_p = sub.add_parser("run", help="Run multi-instrument backtest")
    run_p.add_argument("--strategy", required=True)
    run_p.add_argument("--symbols", default="all")
    run_p.add_argument("--data-root", default=None)
    run_p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_p.add_argument("--start", default=None)
    run_p.add_argument("--end", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "audit":
        return cmd_audit(args)
    if args.command == "list-strategies":
        return cmd_list_strategies(args)
    if args.command == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
