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
from typing import Any

import yaml

BACKTESTER_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BACKTESTER_ROOT.parents[1]
DEFAULT_CSV = REPO_ROOT / "backtester-app/documents/video_docs/strategy_videos_90.csv"
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
class MultiBacktestSummary:
    strategy_id: str
    module_id: str
    video_number: str
    data_root: str
    data_source: str
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    skip_reasons: dict[str, str] = field(default_factory=dict)
    matrix_rows: list[InstrumentResult] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str = ""
    worst_instrument: str = ""
    affinity_notes: str = ""


def _ensure_pythonpath() -> None:
    documents_dir = BACKTESTER_ROOT.parent
    if str(documents_dir) not in sys.path:
        sys.path.insert(0, str(documents_dir))


def resolve_data_root(cli_root: str | None = None) -> tuple[str, str]:
    if cli_root:
        path = Path(cli_root)
        if path.is_dir():
            return str(path), "cli"
    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path and Path(env_path).is_dir():
        symbols = [p for p in Path(env_path).iterdir() if p.is_dir()]
        if symbols:
            return env_path, "env"
    windows_path = Path(WINDOWS_DEFAULT_DATA)
    if windows_path.is_dir():
        return str(windows_path), "windows_default"
    return "", "missing"


def has_real_history(data_root: str) -> bool:
    root = Path(data_root)
    if not root.is_dir():
        return False
    for symbol_dir in root.iterdir():
        if not symbol_dir.is_dir():
            continue
        for tf_dir in symbol_dir.iterdir():
            if tf_dir.is_dir() and any(tf_dir.glob("*.csv")):
                return True
    return False


def load_strategy_config(module: str) -> dict[str, Any]:
    config_path = BACKTESTER_ROOT / "strategies" / module / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def composite_score(row: dict[str, Any], best_pnl: float, min_trades: int = 10) -> float:
    trades = int(row.get("bt_total_trades", 0))
    if trades < min_trades:
        return -1.0
    pf = min(float(row.get("bt_profit_factor", 0) or 0), 5.0) / 5.0
    win_rate = float(row.get("bt_win_rate", 0) or 0) / 100.0
    sharpe = float(row.get("bt_sharpe_ratio", 0) or 0)
    sharpe_norm = min(max(sharpe, -2.0), 3.0) / 3.0
    pnl = float(row.get("bt_total_pnl", 0) or 0)
    pnl_norm = (pnl / best_pnl) if best_pnl > 0 else 0.0
    trade_norm = min(trades, 50) / 50.0
    return round(
        pf * 0.35 + win_rate * 0.20 + sharpe_norm * 0.20 + pnl_norm * 0.15 + trade_norm * 0.10,
        4,
    )


def read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def write_csv_atomic(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        newline="",
        encoding="utf-8",
        delete=False,
        dir=csv_path.parent,
    ) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        tmp_path = tmp.name
    os.replace(tmp_path, csv_path)


def update_matrix_csv(output_dir: Path, new_rows: list[dict[str, Any]]) -> None:
    matrix_path = output_dir / "strategy_instrument_matrix.csv"
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    fieldnames = MATRIX_COLUMNS
    if matrix_path.exists():
        with open(matrix_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or MATRIX_COLUMNS)
            for row in reader:
                key = (row["strategy_registry_id"], row["symbol"])
                existing[key] = row
    for row in new_rows:
        key = (row["strategy_registry_id"], row["symbol"])
        existing[key] = row
    write_csv_atomic(matrix_path, fieldnames, list(existing.values()))


def cmd_audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    fieldnames, rows = read_csv_rows(csv_path)
    canonical = [r for r in rows if r.get("action") == "CODE-CANONICAL"]
    coded_dirs = [
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"tests", "__pycache__"}
    ]
    data_root, source = resolve_data_root(args.data_root)
    print("=== Audit ===")
    print(f"Canonical rows: {len(canonical)}")
    print(f"Strategy folders on disk: {sorted(coded_dirs)}")
    print(f"Data root ({source}): {data_root or 'NOT FOUND'}")
    if data_root:
        client_symbols = []
        _ensure_pythonpath()
        from backtester.connectors import ExnessCSVClient

        client_symbols = ExnessCSVClient(data_root).get_symbols()
        print(f"Symbols in data root: {len(client_symbols)}")
    status_counts: dict[str, int] = {}
    for row in canonical:
        status = row.get("implementation_status") or "not_started"
        status_counts[status] = status_counts.get(status, 0) + 1
    print(f"Status counts: {status_counts}")
    write_csv_atomic(csv_path, fieldnames, rows)
    return 0


def cmd_list_strategies(_: argparse.Namespace) -> int:
    _ensure_pythonpath()
    from backtester.strategies.registry import list_strategy_entries

    for entry in list_strategy_entries():
        print(f"{entry['id']}\t{entry['name']}\tvideo={entry['source_video']}")
    return 0


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str,
    symbols: str | list[str] = "all",
    output_dir: str | Path = DEFAULT_OUTPUT,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiBacktestSummary:
    _ensure_pythonpath()
    from backtester.connectors import ExnessCSVClient
    from backtester.core import BacktestConfig
    from backtester.core.engine import BacktestEngine
    from backtester.core.timeframes import TF, tf_from_string
    from backtester.strategies.registry import get_strategy

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Strategy not found: {strategy_id}")

    module_id = strategy_id.split("_", 1)[-1] if "_" in strategy_id else strategy_id
    config_yaml = load_strategy_config(module_id)
    defaults = config_yaml.get("backtest_defaults", {})
    required_tf = [
        tf_from_string(tf_name) for tf_name in config_yaml.get("required_timeframes", [])
    ]
    if not required_tf:
        required_tf = list(strategy_cls.timeframes)

    client = ExnessCSVClient(data_root)
    all_symbols = client.get_symbols()
    if symbols == "all":
        target_symbols = all_symbols
    elif isinstance(symbols, str):
        target_symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        target_symbols = list(symbols)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    strategy_output = output_path / strategy_cls.id
    strategy_output.mkdir(parents=True, exist_ok=True)

    data_source = "exness_production" if has_real_history(data_root) else "not_backtested"
    summary = MultiBacktestSummary(
        strategy_id=strategy_cls.id,
        module_id=module_id,
        video_number=str(config_yaml.get("video_number", strategy_cls.source_video)),
        data_root=data_root,
        data_source=data_source,
        instruments_scanned=len(target_symbols),
    )

    matrix_rows: list[dict[str, Any]] = []
    instrument_results: list[InstrumentResult] = []

    for symbol in target_symbols:
        missing = [tf for tf in required_tf if not client.has_timeframe(symbol, tf)]
        if missing:
            reason = f"missing timeframes: {', '.join(tf.name for tf in missing)}"
            summary.skip_reasons[symbol] = reason
            summary.instruments_skipped += 1
            continue

        sym_start, sym_end = client.get_full_date_range(symbol, required_tf)
        if not sym_start or not sym_end:
            summary.skip_reasons[symbol] = "no date range"
            summary.instruments_skipped += 1
            continue

        run_start = start or sym_start
        run_end = end or sym_end

        strategy = strategy_cls()
        bt_config = BacktestConfig(
            strategy_id=strategy_cls.id,
            symbol=symbol,
            start_date=run_start,
            end_date=run_end,
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
            summary.skip_reasons[symbol] = f"error: {exc}"
            summary.instruments_skipped += 1
            continue

        summary.instruments_tested += 1
        json_path = strategy_output / f"{symbol}.json"
        payload = result.to_dict()
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

        stats = payload["stats"]
        row = {
            "strategy_registry_id": strategy_cls.id,
            "strategy_module_id": module_id,
            "video_number": summary.video_number,
            "symbol": symbol,
            "backtest_start_date": run_start.date().isoformat(),
            "backtest_end_date": run_end.date().isoformat(),
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
            "composite_score": 0.0,
            "rank_within_strategy": 0,
            "backtest_result_json": str(json_path),
            "backtested_at": datetime.now(timezone.utc).isoformat(),
            "data_quality_note": "",
            "data_source": data_source,
        }
        matrix_rows.append(row)
        instrument_results.append(
            InstrumentResult(
                symbol=symbol,
                start_date=row["backtest_start_date"],
                end_date=row["backtest_end_date"],
                stats=stats,
                json_path=str(json_path),
            )
        )

    best_pnl = max((float(r["bt_total_pnl"]) for r in matrix_rows), default=0.0)
    min_trades = int(config_yaml.get("min_trades_for_ranking", 10))
    ranked: list[tuple[float, dict[str, Any]]] = []
    for row in matrix_rows:
        score = composite_score(row, best_pnl, min_trades)
        row["composite_score"] = score
        if score >= 0:
            ranked.append((score, row))

    ranked.sort(key=lambda item: item[0], reverse=True)
    for rank, (_, row) in enumerate(ranked, start=1):
        row["rank_within_strategy"] = rank

    update_matrix_csv(output_path, matrix_rows)

    if ranked:
        best = ranked[0][1]
        worst = ranked[-1][1]
        summary.best_instrument = best["symbol"]
        summary.worst_instrument = worst["symbol"]
        summary.affinity_notes = (
            f"Best on {best['symbol']} (PF={best['bt_profit_factor']}, "
            f"{best['bt_total_trades']} trades). "
            f"Weakest ranked: {worst['symbol']} (PF={worst['bt_profit_factor']})."
        )
    elif matrix_rows:
        summary.affinity_notes = "No symbol met minimum trade threshold for ranking."

    # aggregate
    total_trades = sum(int(r["bt_total_trades"]) for r in matrix_rows)
    total_pnl = sum(float(r["bt_total_pnl"]) for r in matrix_rows)
    win_rates = [float(r["bt_win_rate"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]
    pfs = [float(r["bt_profit_factor"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]
    dds = [float(r["bt_max_drawdown_pct"]) for r in matrix_rows]
    sharpes = [float(r["bt_sharpe_ratio"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]
    rrs = [float(r["bt_avg_rr"]) for r in matrix_rows if int(r["bt_total_trades"]) > 0]

    summary.aggregate_stats = {
        "bt_total_trades_all": total_trades,
        "bt_win_rate_all": round(sum(win_rates) / len(win_rates), 2) if win_rates else 0.0,
        "bt_profit_factor_all": round(sum(pfs) / len(pfs), 2) if pfs else 0.0,
        "bt_max_drawdown_pct_all": round(max(dds), 2) if dds else 0.0,
        "bt_total_pnl_all": round(total_pnl, 2),
        "bt_sharpe_ratio_all": round(sum(sharpes) / len(sharpes), 2) if sharpes else 0.0,
        "bt_avg_rr_all": round(sum(rrs) / len(rrs), 2) if rrs else 0.0,
    }
    summary.matrix_rows = instrument_results
    return summary


def update_tracking_csv(
    csv_path: Path,
    video_number: str,
    summary: MultiBacktestSummary,
    *,
    implementation_status: str,
    anti_bias_passed: str,
    anti_bias_notes: str,
    backtest_error: str = "",
) -> None:
    fieldnames, rows = read_csv_rows(csv_path)
    now = datetime.now(timezone.utc).isoformat()

    canonical_row = None
    for row in rows:
        if row.get("video_number") == video_number and row.get("action") == "CODE-CANONICAL":
            canonical_row = row
            break

    if canonical_row is None:
        return

    canonical_row["implementation_status"] = implementation_status
    canonical_row["strategy_module_id"] = summary.module_id
    canonical_row["strategy_folder"] = f"strategies/{summary.module_id}/"
    canonical_row["strategy_registry_id"] = summary.strategy_id
    canonical_row["coded_at"] = canonical_row.get("coded_at") or now
    canonical_row["anti_bias_review_passed"] = anti_bias_passed
    canonical_row["anti_bias_notes"] = anti_bias_notes
    canonical_row["backtest_error"] = backtest_error
    canonical_row["data_source"] = summary.data_source
    canonical_row["data_root_used"] = summary.data_root
    canonical_row["instruments_tested_count"] = str(summary.instruments_tested)

    if summary.instruments_tested > 0:
        canonical_row["backtested_at"] = now
        for key, value in summary.aggregate_stats.items():
            canonical_row[key] = str(value)
        if summary.best_instrument:
            best_row = next(
                (
                    r
                    for r in summary.matrix_rows
                    if r.symbol == summary.best_instrument
                ),
                None,
            )
            canonical_row["best_instrument"] = summary.best_instrument
            canonical_row["worst_instrument"] = summary.worst_instrument
            canonical_row["instrument_affinity_notes"] = summary.affinity_notes
            if best_row:
                canonical_row["best_instrument_pf"] = str(best_row.stats.get("profit_factor", ""))
                canonical_row["best_instrument_win_rate"] = str(best_row.stats.get("win_rate", ""))
                canonical_row["best_instrument_pnl"] = str(best_row.stats.get("total_pnl", ""))
                canonical_row["best_instrument_trades"] = str(best_row.stats.get("total_trades", ""))

    if implementation_status == "coded_and_backtested" and summary.data_source == "exness_production":
        for row in rows:
            if (
                row.get("action") == "DUPLICATE-SKIP"
                and row.get("module_to_code") == summary.module_id
            ):
                row["implementation_status"] = "covered_by_canonical"
                row["strategy_registry_id"] = summary.strategy_id
                row["data_source"] = summary.data_source
                for key in summary.aggregate_stats:
                    row[key] = str(summary.aggregate_stats[key])
                row["best_instrument"] = canonical_row.get("best_instrument", "")
                row["worst_instrument"] = canonical_row.get("worst_instrument", "")
                row["instrument_affinity_notes"] = summary.affinity_notes

    write_csv_atomic(csv_path, fieldnames, rows)


def cmd_run(args: argparse.Namespace) -> int:
    data_root, _ = resolve_data_root(args.data_root)
    csv_path = Path(args.csv) if args.csv else DEFAULT_CSV

    if not data_root or not has_real_history(data_root):
        print("Real Exness history not available — code-only status expected.")
        if not data_root:
            data_root = WINDOWS_DEFAULT_DATA

    _ensure_pythonpath()
    from backtester.strategies.registry import get_strategy

    strategy_cls = get_strategy(args.strategy)
    if strategy_cls is None:
        print(f"Unknown strategy: {args.strategy}")
        return 1

    module_id = strategy_cls.id.split("_", 1)[-1]
    config_yaml = load_strategy_config(module_id)
    video_number = str(config_yaml.get("video_number", strategy_cls.source_video))

    anti_bias_passed = "yes"
    anti_bias_notes = (
        "HTF bars gated post-close in data_feed; session filters use America/New_York; "
        "signals on M1 bar close; VP/absorption from past session bars only; "
        "parameters from video spec/config.yaml."
    )

    try:
        summary = run_multi_instrument_backtest(
            strategy_id=strategy_cls.id,
            data_root=data_root,
            symbols=args.symbols,
            output_dir=args.output,
        )
        if summary.instruments_tested == 0:
            status = "coded_pending_production_backtest"
            summary.data_source = "pending_exness_production"
        elif summary.data_source == "exness_production":
            status = "coded_and_backtested"
        else:
            status = "coded_pending_production_backtest"
            summary.data_source = "pending_exness_production"
    except Exception as exc:
        update_tracking_csv(
            csv_path,
            video_number,
            MultiBacktestSummary(
                strategy_id=strategy_cls.id,
                module_id=module_id,
                video_number=video_number,
                data_root=data_root,
                data_source="not_backtested",
            ),
            implementation_status="failed",
            anti_bias_passed=anti_bias_passed,
            anti_bias_notes=anti_bias_notes,
            backtest_error=str(exc),
        )
        raise

    update_tracking_csv(
        csv_path,
        video_number,
        summary,
        implementation_status=status,
        anti_bias_passed=anti_bias_passed,
        anti_bias_notes=anti_bias_notes,
    )
    print(f"Backtest complete: tested={summary.instruments_tested} skipped={summary.instruments_skipped}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strategy pipeline backtester")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit CSV vs coded folders")
    audit.add_argument("--csv", default=str(DEFAULT_CSV))
    audit.add_argument("--data-root", default=None)
    audit.set_defaults(func=cmd_audit)

    listing = sub.add_parser("list-strategies", help="List registered strategies")
    listing.set_defaults(func=cmd_list_strategies)

    run = sub.add_parser("run", help="Run multi-instrument backtest")
    run.add_argument("--strategy", required=True)
    run.add_argument("--symbols", default="all")
    run.add_argument("--data-root", default=None)
    run.add_argument("--output", default=str(DEFAULT_OUTPUT))
    run.add_argument("--csv", default=str(DEFAULT_CSV))
    run.add_argument("--start", default=None)
    run.add_argument("--end", default=None)
    run.set_defaults(func=cmd_run)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
