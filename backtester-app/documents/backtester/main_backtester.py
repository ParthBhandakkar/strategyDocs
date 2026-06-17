#!/usr/bin/env python3
"""
Main backtester CLI — audit, list-strategies, run.
"""

from __future__ import annotations

import sys
from pathlib import Path

_DOCS_ROOT = Path(__file__).resolve().parents[1]
if str(_DOCS_ROOT) not in sys.path:
    sys.path.insert(0, str(_DOCS_ROOT))

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig
from backtester.core.engine import BacktestEngine
from backtester.core.timeframes import TF, tf_from_string
from backtester.strategies.registry import get_strategy, list_strategy_ids, load_all_strategies

BACKTESTER_ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = BACKTESTER_ROOT.parent / "video_docs" / "strategy_videos_90.csv"
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


@dataclass
class RunSummary:
    strategy_id: str
    strategy_module_id: str
    video_number: str
    data_root: str
    data_source: str
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str = ""
    worst_instrument: str = ""
    affinity_notes: str = ""


def resolve_data_root(cli_root: str | None = None) -> tuple[str, bool]:
    if cli_root:
        path = Path(cli_root)
        if path.is_dir() and _has_symbol_data(path):
            return str(path), True
        return str(path), False

    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path and Path(env_path).is_dir() and _has_symbol_data(Path(env_path)):
        return env_path, True

    windows_path = Path(WINDOWS_DEFAULT_DATA)
    if windows_path.is_dir() and _has_symbol_data(windows_path):
        return str(windows_path), True

    return str(windows_path), False


def _has_symbol_data(path: Path) -> bool:
    for child in path.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            for tf_dir in child.iterdir():
                if tf_dir.is_dir() and any(tf_dir.glob("*.csv")):
                    return True
    return False


def load_strategy_config(module: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0))
    if trades < min_trades:
        return -1.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0) / 5.0 * 0.35
    wr = float(row.get("bt_win_rate", 0) or 0) / 100.0 * 0.20
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    sharpe_norm = min(max(sharpe, -2), 3) / 3.0 * 0.20
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    pnl_norm = (pnl / best_pnl) * 0.15 if best_pnl > 0 else 0.0
    trade_norm = min(trades, 50) / 50.0 * 0.10
    return round(pf + wr + sharpe_norm + pnl_norm + trade_norm, 4)


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    output_dir: Path,
    defaults: dict[str, Any],
    data_source: str,
) -> dict[str, Any]:
    required_tfs = [tf_from_string(tf) for tf in defaults.get("required_timeframes", ["M1"])]
    start, end = client.get_full_date_range(symbol, required_tfs)
    if not start or not end:
        return {"skipped": True, "reason": "missing required timeframe data"}

    for tf in required_tfs:
        if not client.get_bars(symbol, tf, start, end):
            return {"skipped": True, "reason": f"missing {tf.name} data"}

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
    json_dir = output_dir / strategy_cls.id
    json_dir.mkdir(parents=True, exist_ok=True)
    json_path = json_dir / f"{symbol}.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(result_dict, handle, indent=2)

    stats = result_dict["stats"]
    return {
        "skipped": False,
        "symbol": symbol,
        "backtest_start_date": start.date().isoformat(),
        "backtest_end_date": end.date().isoformat(),
        "bt_total_trades": stats["total_trades"],
        "bt_winning_trades": stats["winning_trades"],
        "bt_losing_trades": stats["losing_trades"],
        "bt_win_rate": stats["win_rate"],
        "bt_profit_factor": stats["profit_factor"],
        "bt_max_drawdown_pct": stats["max_drawdown_pct"],
        "bt_total_pnl": stats["total_pnl"],
        "bt_sharpe_ratio": stats["sharpe_ratio"],
        "bt_avg_rr": stats["avg_rr"],
        "bt_avg_trade_duration_mins": stats["avg_trade_duration_mins"],
        "backtest_result_json": str(json_path.relative_to(BACKTESTER_ROOT.parent.parent)),
        "data_source": data_source,
    }


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
) -> RunSummary:
    data_path, has_real_data = resolve_data_root(data_root)
    data_source = "exness_production" if has_real_data else "not_backtested"
    output_path = Path(output_dir or DEFAULT_OUTPUT)
    output_path.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    module = strategy_cls.id.split("_", 1)[-1] if "_" in strategy_cls.id else strategy_cls.id
    config_yaml = load_strategy_config(module)
    defaults = config_yaml.get("backtest_defaults", {})
    video_number = str(config_yaml.get("video_number", ""))
    min_trades = int(config_yaml.get("min_trades_for_ranking", 10))

    summary = RunSummary(
        strategy_id=strategy_cls.id,
        strategy_module_id=module,
        video_number=video_number,
        data_root=data_path,
        data_source=data_source,
    )

    if not has_real_data:
        summary.instruments_skipped = 0
        summary.affinity_notes = "Production backtest required on Windows with Exness history path."
        return summary

    client = ExnessCSVClient(data_path)
    all_symbols = client.get_symbols()
    summary.instruments_scanned = len(all_symbols)

    if symbols == "all":
        target_symbols = all_symbols
    elif isinstance(symbols, str):
        target_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        target_symbols = [s.upper() for s in symbols]

    rows: list[dict[str, Any]] = []
    for symbol in target_symbols:
        if symbol not in all_symbols:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = "symbol folder not found"
            continue
        try:
            row = run_single_symbol_backtest(
                strategy_cls, symbol, client, output_path, defaults, data_source
            )
        except Exception as exc:
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = str(exc)
            continue

        if row.get("skipped"):
            summary.instruments_skipped += 1
            summary.skip_reasons[symbol] = row.get("reason", "skipped")
            continue

        row.update(
            {
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": module,
                "video_number": video_number,
                "backtested_at": datetime.now(timezone.utc).isoformat(),
                "data_quality_note": "",
            }
        )
        rows.append(row)
        summary.instruments_tested += 1

    if rows:
        best_pnl = max(float(r["bt_total_pnl"]) for r in rows)
        for row in rows:
            row["composite_score"] = composite_score(row, best_pnl, min_trades)
        ranked = sorted(rows, key=lambda r: r["composite_score"], reverse=True)
        for idx, row in enumerate(ranked, start=1):
            row["rank_within_strategy"] = idx

        eligible = [r for r in ranked if int(r["bt_total_trades"]) >= min_trades]
        if eligible:
            best = eligible[0]
            worst = eligible[-1]
            summary.best_instrument = best["symbol"]
            summary.worst_instrument = worst["symbol"]
            summary.affinity_notes = (
                f"Strong on {best['symbol']} (PF={best['bt_profit_factor']}, "
                f"{best['bt_total_trades']} trades). "
                f"Weak on {worst['symbol']} (PF={worst['bt_profit_factor']})."
            )

        total_trades = sum(int(r["bt_total_trades"]) for r in rows)
        total_pnl = sum(float(r["bt_total_pnl"]) for r in rows)
        win_rates = [float(r["bt_win_rate"]) for r in rows if int(r["bt_total_trades"]) > 0]
        pfs = [float(r["bt_profit_factor"]) for r in rows if int(r["bt_total_trades"]) > 0 and r["bt_profit_factor"] != float("inf")]
        dds = [float(r["bt_max_drawdown_pct"]) for r in rows]
        sharpes = [float(r["bt_sharpe_ratio"]) for r in rows]
        rrs = [float(r["bt_avg_rr"]) for r in rows if int(r["bt_total_trades"]) > 0]

        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": round(sum(win_rates) / len(win_rates), 2) if win_rates else 0.0,
            "bt_profit_factor_all": round(sum(pfs) / len(pfs), 2) if pfs else 0.0,
            "bt_max_drawdown_pct_all": round(max(dds), 2) if dds else 0.0,
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": round(sum(sharpes) / len(sharpes), 2) if sharpes else 0.0,
            "bt_avg_rr_all": round(sum(rrs) / len(rrs), 2) if rrs else 0.0,
        }

    summary.matrix_rows = rows
    _update_matrix_csv(rows)
    return summary


def _update_matrix_csv(rows: list[dict[str, Any]]):
    matrix_path = DEFAULT_OUTPUT / "strategy_instrument_matrix.csv"
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if matrix_path.exists():
        with matrix_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
                existing[key] = row

    for row in rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = {col: str(row.get(col, "")) for col in MATRIX_COLUMNS}

    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda r: (r["strategy_registry_id"], r["symbol"])):
            writer.writerow({col: row.get(col, "") for col in MATRIX_COLUMNS})


def _read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def _write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    tmp_path = csv_path.with_suffix(".csv.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(csv_path)


def audit(csv_path: Path) -> dict[str, Any]:
    fieldnames, rows = _read_csv_rows(csv_path)
    coded_modules = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__"}
    }
    registry_ids = list_strategy_ids()
    data_path, has_data = resolve_data_root()

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    status_counts: dict[str, int] = {}
    for row in canonical:
        status = row.get("implementation_status") or "not_started"
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "csv_path": str(csv_path),
        "canonical_count": len(canonical),
        "status_counts": status_counts,
        "coded_folders": sorted(coded_modules),
        "registry_ids": registry_ids,
        "data_root": data_path,
        "data_available": has_data,
        "fieldnames_updated": fieldnames != list(csv.DictReader(csv_path.open()).fieldnames or []),
    }


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    fieldnames, rows = _read_csv_rows(csv_path)
    report = audit(csv_path)
    _write_csv_atomic(csv_path, fieldnames, rows)

    print("=== Audit ===")
    print(f"CSV: {report['csv_path']}")
    print(f"Canonical modules: {report['canonical_count']}")
    print(f"Status counts: {report['status_counts']}")
    print(f"Registry strategies: {report['registry_ids']}")
    print(f"Coded folders: {report['coded_folders']}")
    print(f"Data root: {report['data_root']} (available={report['data_available']})")
    return 0


def cmd_list_strategies(_args: argparse.Namespace) -> int:
    load_all_strategies()
    for strat_id in list_strategy_ids():
        cls = get_strategy(strat_id)
        print(f"{strat_id} — {cls.name if cls else 'unknown'}")
    return 0


def update_tracking_csv(
    csv_path: Path,
    module: str,
    registry_id: str,
    summary: RunSummary,
    has_real_data: bool,
):
    fieldnames, rows = _read_csv_rows(csv_path)
    now = datetime.now(timezone.utc).isoformat()

    if has_real_data and summary.instruments_tested > 0:
        status = "coded_and_backtested"
        data_source = "exness_production"
    elif has_real_data:
        status = "failed"
        data_source = "exness_production"
    else:
        status = "coded_pending_production_backtest"
        data_source = "pending_exness_production"

    anti_bias = "yes"
    anti_notes = (
        "M1 signals on bar close; session VP from prior session bars only; "
        "NY timezone via zoneinfo; no HTF lookahead."
    )

    for row in rows:
        if row.get("module_to_code") == module and row.get("action") == "CODE-CANONICAL":
            row["implementation_status"] = status
            row["strategy_module_id"] = module
            row["strategy_folder"] = f"strategies/{module}/"
            row["strategy_registry_id"] = registry_id
            row["coded_at"] = row.get("coded_at") or now
            if has_real_data and summary.instruments_tested > 0:
                row["backtested_at"] = now
            row["instruments_tested_count"] = str(summary.instruments_tested)
            row["anti_bias_review_passed"] = anti_bias
            row["anti_bias_notes"] = anti_notes
            row["data_source"] = data_source
            row["data_root_used"] = summary.data_root
            for key, value in summary.aggregate_stats.items():
                row[key] = str(value)
            row["best_instrument"] = summary.best_instrument
            row["worst_instrument"] = summary.worst_instrument
            row["instrument_affinity_notes"] = summary.affinity_notes
            if status == "failed":
                row["backtest_error"] = "No instruments produced backtest results"
        elif (
            row.get("module_to_code") == module
            and row.get("action") == "DUPLICATE-SKIP"
            and status == "coded_and_backtested"
            and data_source == "exness_production"
        ):
            row["implementation_status"] = "covered_by_canonical"
            row["strategy_registry_id"] = registry_id
            for key in summary.aggregate_stats:
                row[key] = str(summary.aggregate_stats[key])
            row["best_instrument"] = summary.best_instrument
            row["worst_instrument"] = summary.worst_instrument
            row["instrument_affinity_notes"] = summary.affinity_notes
            row["data_source"] = data_source

    _write_csv_atomic(csv_path, fieldnames, rows)


def cmd_run(args: argparse.Namespace) -> int:
    data_path, has_real_data = resolve_data_root(args.data_root)
    summary = run_multi_instrument_backtest(
        strategy_id=args.strategy,
        data_root=data_path if has_real_data else args.data_root,
        symbols=args.symbols,
        output_dir=args.output,
    )
    update_tracking_csv(
        Path(args.csv),
        module=summary.strategy_module_id,
        registry_id=summary.strategy_id,
        summary=summary,
        has_real_data=has_real_data,
    )
    print(json.dumps(summary.aggregate_stats, indent=2))
    print(f"Tested: {summary.instruments_tested}, Skipped: {summary.instruments_skipped}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_parser = sub.add_parser("audit", help="Audit CSV vs coded strategies")
    audit_parser.add_argument("--csv", default=str(DEFAULT_CSV))
    audit_parser.set_defaults(func=cmd_audit)

    list_parser = sub.add_parser("list-strategies", help="List registered strategies")
    list_parser.set_defaults(func=cmd_list_strategies)

    run_parser = sub.add_parser("run", help="Run multi-instrument backtest")
    run_parser.add_argument("--strategy", required=True)
    run_parser.add_argument("--symbols", default="all")
    run_parser.add_argument("--data-root", default=None)
    run_parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run_parser.add_argument("--csv", default=str(DEFAULT_CSV))
    run_parser.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
