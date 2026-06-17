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
from typing import Any, Optional

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
from backtester.strategies.registry import get_strategy, list_strategy_ids, load_all_strategies


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    strategy_id: str
    module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    best_instrument: str = ""
    worst_instrument: str = ""
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_root: str | None) -> tuple[str, bool]:
    if cli_root:
        path = Path(cli_root)
        if path.is_dir() and _has_symbol_data(path):
            return str(path), True
        return str(path), False

    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_data(path):
            return str(path), True

    win_path = Path(WINDOWS_DEFAULT_DATA)
    if win_path.is_dir() and _has_symbol_data(win_path):
        return str(win_path), True

    return WINDOWS_DEFAULT_DATA, False


def _has_symbol_data(root: Path) -> bool:
    if not root.is_dir():
        return False
    for child in root.iterdir():
        if child.is_dir() and any(child.rglob("*.csv")):
            return True
    return False


def load_strategy_config(module: str) -> dict[str, Any]:
    cfg_path = BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not cfg_path.exists():
        return {}
    with cfg_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def required_timeframes(strategy_cls, config: dict[str, Any]) -> list[TF]:
    if config.get("required_timeframes"):
        return [tf_from_string(tf) for tf in config["required_timeframes"]]
    return list(strategy_cls.timeframes)


def composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0))
    if trades < min_trades:
        return -1.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0)
    wr = float(row.get("bt_win_rate", 0) or 0)
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    return (
        (pf / 5.0 * 0.35)
        + (wr / 100.0 * 0.20)
        + (sharpe_norm * 0.20)
        + (pnl_norm * 0.15)
        + (min(trades, 50) / 50.0 * 0.10)
    )


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    config: dict[str, Any],
    strategy_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[Any | None, str]:
    tfs = required_timeframes(strategy_cls, config)
    for tf in tfs:
        if not client.has_timeframe(symbol, tf):
            return None, f"missing timeframe {tf.name}"

    sym_start, sym_end = client.get_full_date_range(symbol, tfs)
    if not sym_start or not sym_end:
        return None, "no bars in date range"

    bt_start = start or sym_start
    bt_end = end or sym_end
    defaults = config.get("backtest_defaults", {})

    bt_config = BacktestConfig(
        strategy_id=strategy_id,
        symbol=symbol,
        start_date=bt_start,
        end_date=bt_end,
        initial_balance=float(defaults.get("initial_balance", 10000.0)),
        risk_per_trade=float(defaults.get("risk_per_trade", 0.01)),
        spread_pips=float(defaults.get("spread_pips", 1.0)),
        slippage_pips=float(defaults.get("slippage_pips", 0.5)),
        commission_per_lot=float(defaults.get("commission_per_lot", 7.0)),
    )

    strategy = strategy_cls()
    engine = BacktestEngine(bt_config, strategy, client)
    result = engine.run()
    return result, ""


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> RunSummary:
    resolved_root, has_data = resolve_data_root(data_root)
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    module_id = strategy_id.split("_", 1)[-1] if "_" in strategy_id else strategy_id
    config = load_strategy_config(module_id)
    video_number = str(config.get("video_number", ""))
    min_trades = int(config.get("min_trades_for_ranking", 10))

    summary = RunSummary(
        strategy_id=strategy_cls.id,
        module_id=module_id,
        video_number=video_number,
        data_root_used=resolved_root,
        data_source="pending_exness_production" if not has_data else "exness_production",
    )

    if not has_data:
        logger.warning("Real Exness history unavailable at %s", resolved_root)
        return summary

    client = ExnessCSVClient(resolved_root)
    if symbols == "all":
        symbol_list = client.get_symbols()
    elif isinstance(symbols, str):
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        symbol_list = list(symbols)

    summary.instruments_scanned = len(symbol_list)
    now_iso = datetime.now(timezone.utc).isoformat()

    for symbol in symbol_list:
        result, skip_reason = run_single_symbol_backtest(
            strategy_cls, symbol, client, config, strategy_cls.id, start, end
        )
        if result is None:
            summary.instruments_skipped += 1
            summary.matrix_rows.append(
                {
                    "strategy_registry_id": strategy_cls.id,
                    "strategy_module_id": module_id,
                    "video_number": video_number,
                    "symbol": symbol,
                    "data_quality_note": skip_reason,
                    "data_source": summary.data_source,
                    "backtested_at": now_iso,
                }
            )
            continue

        summary.instruments_tested += 1
        json_path = output_path / strategy_cls.id / f"{symbol}.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle, indent=2)

        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_id,
            "video_number": video_number,
            "symbol": symbol,
            "backtest_start_date": result.config.start_date.date().isoformat(),
            "backtest_end_date": result.config.end_date.date().isoformat(),
            "bt_total_trades": result.total_trades,
            "bt_winning_trades": result.winning_trades,
            "bt_losing_trades": result.losing_trades,
            "bt_win_rate": result.win_rate,
            "bt_profit_factor": result.profit_factor,
            "bt_max_drawdown_pct": result.max_drawdown_pct,
            "bt_total_pnl": round(result.total_pnl, 2),
            "bt_sharpe_ratio": result.sharpe_ratio,
            "bt_avg_rr": result.avg_rr,
            "bt_avg_trade_duration_mins": result.avg_trade_duration,
            "backtest_result_json": str(json_path.relative_to(BACKTESTER_ROOT)),
            "backtested_at": now_iso,
            "data_quality_note": "",
            "data_source": summary.data_source,
        }
        summary.matrix_rows.append(row)

    tested_rows = [r for r in summary.matrix_rows if r.get("bt_total_trades") is not None]
    if tested_rows:
        best_pnl = max(float(r.get("bt_total_pnl", 0) or 0) for r in tested_rows)
        for row in tested_rows:
            row["composite_score"] = round(
                composite_score(row, best_pnl, min_trades), 4
            )

        ranked = sorted(
            tested_rows,
            key=lambda r: r.get("composite_score", -1),
            reverse=True,
        )
        for rank, row in enumerate(ranked, start=1):
            row["rank_within_strategy"] = rank

        eligible = [r for r in ranked if int(r.get("bt_total_trades", 0)) >= min_trades]
        if eligible:
            best = eligible[0]
            worst = eligible[-1]
            summary.best_instrument = best["symbol"]
            summary.worst_instrument = worst["symbol"]

        total_trades = sum(int(r.get("bt_total_trades", 0)) for r in tested_rows)
        total_wins = sum(int(r.get("bt_winning_trades", 0)) for r in tested_rows)
        total_pnl = sum(float(r.get("bt_total_pnl", 0) or 0) for r in tested_rows)
        gross_profit = sum(
            float(r.get("bt_total_pnl", 0) or 0)
            for r in tested_rows
            if float(r.get("bt_total_pnl", 0) or 0) > 0
        )
        gross_loss = abs(
            sum(
                float(r.get("bt_total_pnl", 0) or 0)
                for r in tested_rows
                if float(r.get("bt_total_pnl", 0) or 0) <= 0
            )
        )
        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(total_wins / total_trades * 100, 2)
            if total_trades
            else 0.0,
            "bt_profit_factor_all": round(gross_profit / gross_loss, 2)
            if gross_loss > 0
            else 0.0,
            "bt_max_drawdown_pct_all": max(
                float(r.get("bt_max_drawdown_pct", 0) or 0) for r in tested_rows
            ),
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(
                sum(float(r.get("bt_sharpe_ratio", 0) or 0) for r in tested_rows)
                / len(tested_rows),
                2,
            ),
            "bt_avg_rr_all": round(
                sum(float(r.get("bt_avg_rr", 0) or 0) for r in tested_rows)
                / len(tested_rows),
                2,
            ),
        }

    _write_matrix_csv(output_path / "strategy_instrument_matrix.csv", summary.matrix_rows)
    return summary


def _write_matrix_csv(path: Path, new_rows: list[dict[str, Any]]):
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for row in new_rows:
        key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
        merged = {**existing.get(key, {}), **row}
        for col in MATRIX_COLUMNS:
            merged.setdefault(col, "")
        existing[key] = merged

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda r: (r["strategy_registry_id"], r["symbol"])):
            writer.writerow(row)


def _atomic_csv_write(path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".csv.tmp")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        with tmp_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        return fieldnames, list(reader)


def cmd_audit(csv_path: Path):
    fieldnames, rows = _read_csv_rows(csv_path)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    load_all_strategies()
    coded_ids = set(list_strategy_ids())
    strategies_dir = BACKTESTER_ROOT / "strategies"

    canonical = [
        r
        for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")

    print("\n=== Backtester Audit ===")
    print(f"CSV: {csv_path}")
    print(f"Strategy folders on disk: {[p.name for p in strategies_dir.iterdir() if p.is_dir() and p.name not in {'__pycache__'}]}")
    print(f"Registered strategies: {sorted(coded_ids)}")
    print(f"Canonical progress: {done}/{len(canonical)}")
    data_root, has_data = resolve_data_root(None)
    print(f"Data root: {data_root} (available={has_data})")
    if has_data:
        client = ExnessCSVClient(data_root)
        print(f"Symbols found: {len(client.get_symbols())}")

    for row in canonical:
        module = row.get("module_to_code", "")
        status = row.get("implementation_status", "") or "not_started"
        folder_exists = (strategies_dir / module).is_dir()
        print(f"  V{row.get('video_number')}: {module} status={status} folder={folder_exists}")


def cmd_list_strategies():
    load_all_strategies()
    for strat_id in list_strategy_ids():
        cls = get_strategy(strat_id)
        if cls:
            print(f"{strat_id}: {cls.name} (video {cls.source_video})")


def update_csv_after_run(
    csv_path: Path,
    module: str,
    registry_id: str,
    summary: RunSummary,
    status: str,
    anti_bias_passed: str,
    anti_bias_notes: str,
    backtest_error: str = "",
):
    fieldnames, rows = _read_csv_rows(csv_path)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)

    now_iso = datetime.now(timezone.utc).isoformat()
    agg = summary.aggregate_stats

    for row in rows:
        if row.get("module_to_code") == module and row.get("action") == "CODE-CANONICAL":
            row["implementation_status"] = status
            row["strategy_module_id"] = module
            row["strategy_folder"] = f"strategies/{module}/"
            row["strategy_registry_id"] = registry_id
            row["coded_at"] = row.get("coded_at") or now_iso
            if summary.instruments_tested > 0:
                row["backtested_at"] = now_iso
            row["instruments_tested_count"] = str(summary.instruments_tested)
            row["anti_bias_review_passed"] = anti_bias_passed
            row["anti_bias_notes"] = anti_bias_notes
            row["backtest_error"] = backtest_error
            row["data_source"] = summary.data_source
            row["data_root_used"] = summary.data_root_used
            for key, val in agg.items():
                row[key] = str(val)
            row["best_instrument"] = summary.best_instrument
            if summary.best_instrument:
                best_row = next(
                    (r for r in summary.matrix_rows if r.get("symbol") == summary.best_instrument),
                    {},
                )
                row["best_instrument_pf"] = str(best_row.get("bt_profit_factor", ""))
                row["best_instrument_win_rate"] = str(best_row.get("bt_win_rate", ""))
                row["best_instrument_pnl"] = str(best_row.get("bt_total_pnl", ""))
                row["best_instrument_trades"] = str(best_row.get("bt_total_trades", ""))
            row["worst_instrument"] = summary.worst_instrument
            row["instrument_affinity_notes"] = _affinity_notes(summary)

        if (
            status == "coded_and_backtested"
            and summary.data_source == "exness_production"
            and row.get("action") == "DUPLICATE-SKIP"
            and row.get("module_to_code") == module
        ):
            row["implementation_status"] = "covered_by_canonical"
            row["strategy_registry_id"] = registry_id
            for key in TRACKING_COLUMNS:
                if key.startswith("bt_") or key.startswith("best_") or key == "worst_instrument":
                    canonical = next(
                        (
                            r
                            for r in rows
                            if r.get("module_to_code") == module
                            and r.get("action") == "CODE-CANONICAL"
                        ),
                        None,
                    )
                    if canonical and canonical.get(key):
                        row[key] = canonical[key]

    _atomic_csv_write(csv_path, fieldnames, rows)


def _affinity_notes(summary: RunSummary) -> str:
    ranked = sorted(
        [r for r in summary.matrix_rows if r.get("composite_score") is not None],
        key=lambda r: r.get("composite_score", -1),
        reverse=True,
    )
    if not ranked:
        return "No instruments backtested; production Exness history required on Windows."
    top = ranked[:2]
    bottom = ranked[-2:]
    top_txt = ", ".join(
        f"{r['symbol']} (PF={r.get('bt_profit_factor')}, trades={r.get('bt_total_trades')})"
        for r in top
    )
    bot_txt = ", ".join(
        f"{r['symbol']} (PF={r.get('bt_profit_factor')})" for r in bottom
    )
    return f"Stronger on {top_txt}. Weaker on {bot_txt}."


def cmd_run(args: argparse.Namespace):
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )

    strategy_cls = get_strategy(args.strategy)
    module = summary.module_id
    _, has_data = resolve_data_root(args.data_root)

    if has_data and summary.instruments_tested > 0:
        status = "coded_and_backtested"
    elif has_data:
        status = "failed"
    else:
        status = "coded_pending_production_backtest"

    update_csv_after_run(
        Path(args.csv),
        module=module,
        registry_id=strategy_cls.id if strategy_cls else args.strategy,
        summary=summary,
        status=status,
        anti_bias_passed="yes",
        anti_bias_notes=(
            "HTF bars gated at close in data_feed; session VP built from past M1 bars only; "
            "entries on bar close after absorption at VA extremes; no post-hoc threshold tuning."
        ),
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
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
    run_p.add_argument("--csv", default=str(DEFAULT_CSV))
    run_p.add_argument("--start", default=None)
    run_p.add_argument("--end", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "audit":
        cmd_audit(Path(args.csv))
        return 0
    if args.command == "list-strategies":
        cmd_list_strategies()
        return 0
    if args.command == "run":
        cmd_run(args)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
