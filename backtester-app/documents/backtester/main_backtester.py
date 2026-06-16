#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, run multi-instrument backtests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_DOCS_ROOT = Path(__file__).resolve().parent.parent
if str(_DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(_DOCS_ROOT))

import argparse
import csv
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig, BacktestResult
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_all_strategies, get_strategy, load_all_strategies

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

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
    result: BacktestResult
    composite_score: float = 0.0
    rank: int = 0
    data_quality_note: str = ""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


@dataclass
class MultiBacktestSummary:
    strategy_id: str
    module_id: str
    video_number: str
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    best_instrument: Optional[str] = None
    worst_instrument: Optional[str] = None
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_root: str | None = None) -> tuple[str, bool]:
    """Return (path, exists_with_data)."""
    if cli_root:
        root = Path(cli_root)
        if root.is_dir() and _has_symbol_folders(root):
            return str(root), True
        return str(root), False

    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        root = Path(env_path)
        if root.is_dir() and _has_symbol_folders(root):
            return str(root), True

    default = Path(DEFAULT_WINDOWS_DATA_ROOT)
    if default.is_dir() and _has_symbol_folders(default):
        return str(default), True

    return DEFAULT_WINDOWS_DATA_ROOT, False


def _has_symbol_folders(root: Path) -> bool:
    return any(p.is_dir() for p in root.iterdir() if not p.name.startswith("."))


def strategy_module_name(strategy_cls) -> str:
    parts = strategy_cls.__module__.split(".")
    if len(parts) >= 2 and parts[-1] == "strategy":
        return parts[-2]
    return parts[-1]


def load_strategy_config(module_name: str) -> dict[str, Any]:
    cfg_path = Path(__file__).parent / "strategies" / module_name / "config.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def parse_required_timeframes(strategy_cls, config: dict) -> list[TF]:
    raw = config.get("required_timeframes") or [
        tf_from_string(t) if isinstance(t, str) else t for t in []
    ]
    if not raw and strategy_cls.timeframes:
        return list(strategy_cls.timeframes)
    tfs: list[TF] = []
    for item in raw:
        if isinstance(item, TF):
            tfs.append(item)
        else:
            tfs.append(tf_from_string(str(item)))
    return tfs


def composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0))
    if trades < min_trades:
        return 0.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0) / 5.0 * 0.35
    wr = float(row.get("bt_win_rate", 0) or 0) / 100.0 * 0.20
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    sharpe_norm = min(max(sharpe, -2), 3) / 3.0 * 0.20
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    pnl_norm = (pnl / best_pnl * 0.15) if best_pnl > 0 else 0.0
    trade_norm = min(trades, 50) / 50.0 * 0.10
    return round(pf + wr + sharpe_norm + pnl_norm + trade_norm, 4)


def run_single_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    start: datetime,
    end: datetime,
    defaults: dict[str, Any],
) -> BacktestResult:
    config = BacktestConfig(
        strategy_id=strategy_cls.id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=float(defaults.get("initial_balance", 10000)),
        risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(defaults.get("spread_pips", 1.0)),
        slippage_pips=float(defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
    )
    strategy = strategy_cls()
    engine = BacktestEngine(config, strategy, client)
    return engine.run()


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiBacktestSummary:
    root_path, has_data = resolve_data_root(data_root)
    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module_name = strategy_module_name(strategy_cls)
    config = load_strategy_config(module_name)
    defaults = config.get("backtest_defaults", {})
    required_tfs = parse_required_timeframes(strategy_cls, config)
    min_trades = int(config.get("min_trades_for_ranking", 10))
    video_number = str(config.get("video_number", ""))

    summary = MultiBacktestSummary(
        strategy_id=strategy_cls.id,
        module_id=module_name,
        video_number=video_number,
        data_root_used=root_path,
    )

    if not has_data:
        summary.data_source = "pending_exness_production"
        logger.warning("No real Exness data at %s — skipping backtest runs", root_path)
        return summary

    client = ExnessCSVClient(root_path)
    all_symbols = client.get_symbols()
    summary.instruments_scanned = len(all_symbols)

    if symbols == "all":
        target_symbols = all_symbols
    elif isinstance(symbols, str):
        target_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        target_symbols = [s.upper() for s in symbols]

    results: list[InstrumentResult] = []
    for symbol in target_symbols:
        if not client.has_required_timeframes(symbol, required_tfs):
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = f"missing timeframes: {[tf.name for tf in required_tfs]}"
            continue

        sym_start, sym_end = client.get_full_date_range(symbol, required_tfs)
        if sym_start is None or sym_end is None:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = "no date range"
            continue

        run_start = start or sym_start
        run_end = end or sym_end

        try:
            bt_result = run_single_backtest(
                strategy_cls, symbol, client, run_start, run_end, defaults
            )
            results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=bt_result,
                    start_date=run_start,
                    end_date=run_end,
                )
            )
            summary.instruments_tested += 1
        except Exception as exc:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = str(exc)
            logger.error("Backtest failed for %s: %s", symbol, exc)

    if not results:
        summary.data_source = "pending_exness_production"
        return summary

    summary.data_source = "exness_production"
    best_pnl = max(r.result.total_pnl for r in results) if results else 0.0
    now_iso = datetime.now(timezone.utc).isoformat()

    for ir in results:
        stats = ir.result
        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_name,
            "video_number": video_number,
            "symbol": ir.symbol,
            "backtest_start_date": ir.start_date.date().isoformat() if ir.start_date else "",
            "backtest_end_date": ir.end_date.date().isoformat() if ir.end_date else "",
            "bt_total_trades": stats.total_trades,
            "bt_winning_trades": stats.winning_trades,
            "bt_losing_trades": stats.losing_trades,
            "bt_win_rate": stats.win_rate,
            "bt_profit_factor": stats.profit_factor if stats.profit_factor != float("inf") else 999.0,
            "bt_max_drawdown_pct": stats.max_drawdown_pct,
            "bt_total_pnl": stats.total_pnl,
            "bt_sharpe_ratio": stats.sharpe_ratio,
            "bt_avg_rr": stats.avg_rr,
            "bt_avg_trade_duration_mins": stats.avg_trade_duration,
            "data_quality_note": "",
            "data_source": "exness_production",
            "backtested_at": now_iso,
        }
        row["composite_score"] = composite_score(row, best_pnl, min_trades)
        ir.composite_score = row["composite_score"]
        summary.matrix_rows.append(row)

    ranked = sorted(results, key=lambda r: r.composite_score, reverse=True)
    for rank, ir in enumerate(ranked, start=1):
        ir.rank = rank
        for row in summary.matrix_rows:
            if row["symbol"] == ir.symbol:
                row["rank_within_strategy"] = rank

    eligible = [r for r in ranked if r.result.total_trades >= min_trades]
    if eligible:
        best = eligible[0]
        worst = eligible[-1]
        summary.best_instrument = best.symbol
        summary.worst_instrument = worst.symbol

    total_trades = sum(r.result.total_trades for r in results)
    total_wins = sum(r.result.winning_trades for r in results)
    total_pnl = sum(r.result.total_pnl for r in results)
    pfs = [r.result.profit_factor for r in results if r.result.total_trades > 0 and r.result.profit_factor != float("inf")]
    dds = [r.result.max_drawdown_pct for r in results]
    sharpes = [r.result.sharpe_ratio for r in results if r.result.total_trades > 0]
    avg_rrs = [r.result.avg_rr for r in results if r.result.total_trades > 0]

    summary.aggregate_stats = {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": round(total_wins / total_trades * 100, 2) if total_trades else 0,
        "bt_profit_factor_all": round(sum(pfs) / len(pfs), 2) if pfs else 0,
        "bt_max_drawdown_pct_all": round(max(dds), 2) if dds else 0,
        "bt_total_pnl_all": round(total_pnl, 2),
        "bt_sharpe_ratio_all": round(sum(sharpes) / len(sharpes), 2) if sharpes else 0,
        "bt_avg_rr_all": round(sum(avg_rrs) / len(avg_rrs), 2) if avg_rrs else 0,
    }

    if output_dir:
        _persist_results(summary, results, output_dir, strategy_cls.id)

    return summary


def _persist_results(
    summary: MultiBacktestSummary,
    results: list[InstrumentResult],
    output_dir: str,
    strategy_id: str,
):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    strat_dir = out / strategy_id
    strat_dir.mkdir(parents=True, exist_ok=True)

    for ir in results:
        json_path = strat_dir / f"{ir.symbol}.json"
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(ir.result.to_dict(), fh, indent=2)

    matrix_path = out / "strategy_instrument_matrix.csv"
    _update_matrix_csv(matrix_path, summary.matrix_rows)


def _update_matrix_csv(path: Path, new_rows: list[dict[str, Any]]):
    existing: dict[tuple[str, str], dict] = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for row in new_rows:
        for col in MATRIX_COLUMNS:
            row.setdefault(col, "")
        if "backtest_result_json" not in row or not row["backtest_result_json"]:
            row["backtest_result_json"] = str(
                Path("results") / row["strategy_registry_id"] / f"{row['symbol']}.json"
            )
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = row

    all_rows = list(existing.values())
    fd, tmp = tempfile.mkstemp(suffix=".csv", dir=path.parent)
    os.close(fd)
    try:
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_rows)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def cmd_audit(csv_path: str):
    registry = load_all_strategies()
    coded_modules = {strategy_module_name(cls) for cls in registry.values()}

    rows, fieldnames = _read_csv(csv_path)
    fieldnames = _ensure_columns(fieldnames, TRACKING_COLUMNS)

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")

    print(f"Canonical modules: {len(canonical)}")
    print(f"Coded folders on disk: {len(coded_modules)} -> {sorted(coded_modules)}")
    print(f"Registry strategies: {len(registry)} -> {sorted(registry.keys())}")
    print(f"Complete (coded_and_backtested): {done}/{len(canonical)}")

    data_root, has_data = resolve_data_root()
    print(f"Data root: {data_root} (available={has_data})")
    if has_data:
        client = ExnessCSVClient(data_root)
        print(f"Symbols available: {len(client.get_symbols())}")

    for r in canonical:
        mod = r.get("module_to_code", "")
        status = r.get("implementation_status", "not_started") or "not_started"
        on_disk = "yes" if mod in coded_modules else "no"
        print(f"  V{r.get('video_number')} {mod}: status={status}, on_disk={on_disk}")


def cmd_list_strategies():
    for cls in get_all_strategies():
        print(f"{cls.id}  ({strategy_module_name(cls)})  —  {cls.name}")


def _read_csv(path: str) -> tuple[list[dict], list[str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        return list(reader), fieldnames


def _ensure_columns(fieldnames: list[str], columns: list[str]) -> list[str]:
    for col in columns:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames


def _write_csv_atomic(path: str, rows: list[dict], fieldnames: list[str]):
    p = Path(path)
    fd, tmp = tempfile.mkstemp(suffix=".csv", dir=p.parent)
    os.close(fd)
    try:
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def update_tracking_csv(
    csv_path: str,
    video_number: str,
    updates: dict[str, str],
    propagate_duplicate: bool = False,
):
    rows, fieldnames = _read_csv(csv_path)
    fieldnames = _ensure_columns(fieldnames, TRACKING_COLUMNS)
    canonical_row = None

    for row in rows:
        if row.get("video_number") == str(video_number) and row.get("action") == "CODE-CANONICAL":
            row.update(updates)
            canonical_row = row

    if propagate_duplicate and canonical_row and updates.get("data_source") == "exness_production":
        mod = canonical_row.get("module_to_code", "")
        for row in rows:
            if row.get("action") == "DUPLICATE-SKIP" and row.get("module_to_code") == mod:
                row["implementation_status"] = "covered_by_canonical"
                for key in TRACKING_COLUMNS:
                    if key in updates and key not in ("implementation_status",):
                        row[key] = updates[key]

    _write_csv_atomic(csv_path, rows, fieldnames)


def cmd_run(args):
    output_dir = args.output or str(Path(__file__).parent / "results")
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=output_dir,
    )
    print(json.dumps({
        "strategy_id": summary.strategy_id,
        "instruments_tested": summary.instruments_tested,
        "data_source": summary.data_source,
        "best_instrument": summary.best_instrument,
        "aggregate": summary.aggregate_stats,
    }, indent=2))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Faiz SMC Strategy Backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit_p.add_argument("--csv", required=True)

    sub.add_parser("list-strategies", help="List registered strategies")

    run_p = sub.add_parser("run", help="Run multi-instrument backtest")
    run_p.add_argument("--strategy", required=True)
    run_p.add_argument("--symbols", default="all")
    run_p.add_argument("--data-root", default=None)
    run_p.add_argument("--output", default=None)
    run_p.add_argument("--start", default=None)
    run_p.add_argument("--end", default=None)

    args = parser.parse_args(argv)

    if args.command == "audit":
        cmd_audit(args.csv)
    elif args.command == "list-strategies":
        cmd_list_strategies()
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.error(f"Unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
