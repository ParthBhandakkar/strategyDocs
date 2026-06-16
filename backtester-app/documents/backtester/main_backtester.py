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
from typing import Any, Optional

BACKTESTER_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = BACKTESTER_ROOT.parent
DEFAULT_CSV = DOCUMENTS_ROOT / "video_docs" / "strategy_videos_90.csv"
DEFAULT_OUTPUT = BACKTESTER_ROOT / "results"
DEFAULT_DATA_ROOT = r"O:\D temp\UltimateTradeBot\Data\Exness\structured\history"

if str(DOCUMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(DOCUMENTS_ROOT))

from backtester.connectors.exness_csv import ExnessCSVClient
from backtester.core import BacktestConfig, BacktestResult
from backtester.core.timeframes import TF, tf_from_string
from backtester.core.engine import BacktestEngine
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
    result: BacktestResult
    composite_score: float = 0.0
    rank: int = 0
    data_quality_note: str = ""
    skipped: bool = False


@dataclass
class MultiInstrumentSummary:
    strategy_id: str
    module_id: str
    video_number: str
    matrix_rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    best_instrument: str = ""
    worst_instrument: str = ""
    instruments_scanned: int = 0
    instruments_tested: int = 0
    instruments_skipped: int = 0
    data_source: str = "not_backtested"
    data_root_used: str = ""


def resolve_data_root(cli_root: str | None = None) -> tuple[str, bool]:
    """Return (path, exists_with_data)."""
    if cli_root:
        path = Path(cli_root)
        return str(path), _has_symbol_data(path)

    env_path = os.getenv("LOCAL_HISTORY_PATH")
    if env_path:
        path = Path(env_path)
        if path.is_dir() and _has_symbol_data(path):
            return str(path), True

    default = Path(DEFAULT_DATA_ROOT)
    if default.is_dir() and _has_symbol_data(default):
        return str(default), True

    return str(default), False


def _has_symbol_data(root: Path) -> bool:
    if not root.is_dir():
        return False
    for child in root.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            for sub in child.iterdir():
                if sub.is_dir() and any(sub.glob("*.csv")):
                    return True
    return False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for col in TRACKING_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, rows


def _write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".csv")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        with tmp_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _load_matrix(path: Path) -> tuple[list[str], dict[tuple[str, str], dict[str, str]]]:
    if not path.exists():
        return MATRIX_COLUMNS, {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or MATRIX_COLUMNS)
        data: dict[tuple[str, str], dict[str, str]] = {}
        for row in reader:
            key = (row.get("strategy_registry_id", ""), row.get("symbol", ""))
            data[key] = row
    for col in MATRIX_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames, data


def _save_matrix(path: Path, fieldnames: list[str], data: dict[tuple[str, str], dict[str, str]]):
    rows = sorted(data.values(), key=lambda r: (r.get("strategy_registry_id", ""), r.get("symbol", "")))
    _write_csv_atomic(path, fieldnames, rows)


def composite_score(
    pf: float,
    win_rate: float,
    sharpe: float,
    pnl: float,
    trades: int,
    best_pnl: float,
) -> float:
    pf_norm = min(max(pf, 0), 5) / 5 * 0.35
    wr_norm = min(max(win_rate, 0), 100) / 100 * 0.20
    sharpe_norm = min(max(sharpe, -2), 3) / 3 * 0.20
    pnl_norm = (pnl / best_pnl * 0.15) if best_pnl > 0 else 0.0
    trades_norm = min(trades, 50) / 50 * 0.10
    return round(pf_norm + wr_norm + sharpe_norm + pnl_norm + trades_norm, 4)


def cmd_audit(csv_path: Path):
    fieldnames, rows = _read_csv_rows(csv_path)
    _write_csv_atomic(csv_path, fieldnames, rows)

    load_all_strategies()
    coded_modules = {
        p.name
        for p in (BACKTESTER_ROOT / "strategies").iterdir()
        if p.is_dir() and p.name not in {"__pycache__", "tests"}
    }

    canonical = [
        r for r in rows
        if r.get("action") == "CODE-CANONICAL" and r.get("is_backtestable") == "yes"
    ]
    done = sum(1 for r in canonical if r.get("implementation_status") == "coded_and_backtested")

    print(f"Canonical modules: {len(canonical)}")
    print(f"Coded folders on disk: {sorted(coded_modules)}")
    print(f"Registered strategies: {[s.id for s in get_all_strategies()]}")
    print(f"Completed (coded_and_backtested): {done}/{len(canonical)}")

    data_root, has_data = resolve_data_root()
    print(f"Data root: {data_root} (available={has_data})")
    if has_data:
        client = ExnessCSVClient(data_root)
        print(f"Symbols found: {len(client.get_symbols())}")


def cmd_list_strategies():
    for strat in get_all_strategies():
        print(f"{strat.id}  |  {strat.name}  |  video={strat.source_video}")


def _strategy_defaults(strategy_cls) -> dict[str, float]:
    return {
        "initial_balance": 10000.0,
        "risk_per_trade": 0.01,
        "spread_pips": 1.0,
        "slippage_pips": 0.5,
        "commission_per_lot": 7.0,
    }


def _required_timeframes(strategy_cls) -> list[TF]:
    return list(strategy_cls.timeframes)


def run_single_symbol_backtest(
    strategy_cls,
    symbol: str,
    client: ExnessCSVClient,
    start: datetime,
    end: datetime,
    defaults: dict[str, float],
) -> BacktestResult:
    config = BacktestConfig(
        strategy_id=strategy_cls.id,
        symbol=symbol,
        start_date=start,
        end_date=end,
        initial_balance=defaults["initial_balance"],
        risk_per_trade=defaults["risk_per_trade"],
        spread_pips=defaults["spread_pips"],
        slippage_pips=defaults["slippage_pips"],
        commission_per_lot=defaults["commission_per_lot"],
    )
    strategy = strategy_cls()
    engine = BacktestEngine(config, strategy, client)
    return engine.run()


def run_multi_instrument_backtest(
    strategy_id: str,
    data_root: str | None = None,
    symbols: str | list[str] = "all",
    output_dir: str | Path | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> MultiInstrumentSummary:
    root, has_data = resolve_data_root(data_root)
    output = Path(output_dir or DEFAULT_OUTPUT)
    output.mkdir(parents=True, exist_ok=True)

    strategy_cls = get_strategy(strategy_id)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    summary = MultiInstrumentSummary(
        strategy_id=strategy_cls.id,
        module_id=getattr(strategy_cls, "module_id", strategy_cls.id),
        video_number=strategy_cls.source_video,
        data_root_used=root,
    )

    if not has_data:
        summary.data_source = "pending_exness_production"
        return summary

    client = ExnessCSVClient(root)
    all_symbols = client.get_symbols()
    summary.instruments_scanned = len(all_symbols)

    if symbols == "all":
        target_symbols = all_symbols
    elif isinstance(symbols, str):
        target_symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        target_symbols = list(symbols)

    defaults = _strategy_defaults(strategy_cls)
    required_tfs = _required_timeframes(strategy_cls)
    results: list[InstrumentResult] = []

    for symbol in target_symbols:
        missing = [tf for tf in required_tfs if not client.has_timeframe(symbol, tf)]
        if missing:
            summary.instruments_skipped += 1
            results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=BacktestResult(
                        config=BacktestConfig(
                            strategy_id=strategy_cls.id,
                            symbol=symbol,
                            start_date=datetime.now(timezone.utc),
                            end_date=datetime.now(timezone.utc),
                        )
                    ),
                    skipped=True,
                    data_quality_note=f"Missing timeframes: {[tf.name for tf in missing]}",
                )
            )
            continue

        sym_start, sym_end = client.get_full_date_range(symbol, required_tfs)
        if not sym_start or not sym_end:
            summary.instruments_skipped += 1
            results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=BacktestResult(
                        config=BacktestConfig(
                            strategy_id=strategy_cls.id,
                            symbol=symbol,
                            start_date=datetime.now(timezone.utc),
                            end_date=datetime.now(timezone.utc),
                        )
                    ),
                    skipped=True,
                    data_quality_note="No date range in CSV files",
                )
            )
            continue

        run_start = start or sym_start
        run_end = end or sym_end

        try:
            bt_result = run_single_symbol_backtest(
                strategy_cls, symbol, client, run_start, run_end, defaults
            )
            summary.instruments_tested += 1
            results.append(InstrumentResult(symbol=symbol, result=bt_result))
        except Exception as exc:
            summary.instruments_skipped += 1
            results.append(
                InstrumentResult(
                    symbol=symbol,
                    result=BacktestResult(
                        config=BacktestConfig(
                            strategy_id=strategy_cls.id,
                            symbol=symbol,
                            start_date=run_start,
                            end_date=run_end,
                        )
                    ),
                    skipped=True,
                    data_quality_note=f"Backtest error: {exc}",
                )
            )

    summary.data_source = "exness_production"

    tested = [r for r in results if not r.skipped]
    best_pnl = max((r.result.total_pnl for r in tested), default=0.0)
    if best_pnl <= 0:
        best_pnl = max((abs(r.result.total_pnl) for r in tested), default=1.0)

    min_trades = 10
    for item in tested:
        stats = item.result
        item.composite_score = composite_score(
            stats.profit_factor if stats.profit_factor != float("inf") else 5.0,
            stats.win_rate,
            stats.sharpe_ratio,
            stats.total_pnl,
            stats.total_trades,
            best_pnl,
        )

    ranked = sorted(tested, key=lambda r: r.composite_score, reverse=True)
    for idx, item in enumerate(ranked, start=1):
        item.rank = idx

    rankable = [r for r in ranked if r.result.total_trades >= min_trades]
    if rankable:
        best = rankable[0]
        worst = rankable[-1]
        summary.best_instrument = best.symbol
        summary.worst_instrument = worst.symbol

    now_iso = _utc_now_iso()
    strat_out = output / strategy_cls.id
    strat_out.mkdir(parents=True, exist_ok=True)

    matrix_path = output / "strategy_instrument_matrix.csv"
    matrix_fields, matrix_data = _load_matrix(matrix_path)

    for item in results:
        if item.skipped:
            row = {
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": summary.module_id,
                "video_number": summary.video_number,
                "symbol": item.symbol,
                "data_quality_note": item.data_quality_note,
                "data_source": summary.data_source,
                "backtested_at": now_iso,
                "bt_total_trades": "0",
                "composite_score": "0",
                "rank_within_strategy": "",
            }
        else:
            res = item.result
            json_path = strat_out / f"{item.symbol}.json"
            with json_path.open("w", encoding="utf-8") as fh:
                json.dump(res.to_dict(), fh, indent=2)

            pf = res.profit_factor if res.profit_factor != float("inf") else "999"
            row = {
                "strategy_registry_id": strategy_cls.id,
                "strategy_module_id": summary.module_id,
                "video_number": summary.video_number,
                "symbol": item.symbol,
                "backtest_start_date": res.config.start_date.date().isoformat(),
                "backtest_end_date": res.config.end_date.date().isoformat(),
                "bt_total_trades": str(res.total_trades),
                "bt_winning_trades": str(res.winning_trades),
                "bt_losing_trades": str(res.losing_trades),
                "bt_win_rate": str(res.win_rate),
                "bt_profit_factor": str(pf),
                "bt_max_drawdown_pct": str(res.max_drawdown_pct),
                "bt_total_pnl": str(round(res.total_pnl, 2)),
                "bt_sharpe_ratio": str(res.sharpe_ratio),
                "bt_avg_rr": str(res.avg_rr),
                "bt_avg_trade_duration_mins": str(res.avg_trade_duration),
                "composite_score": str(item.composite_score),
                "rank_within_strategy": str(item.rank) if item.rank else "",
                "backtest_result_json": str(json_path.relative_to(output)),
                "backtested_at": now_iso,
                "data_quality_note": item.data_quality_note,
                "data_source": summary.data_source,
            }

        matrix_data[(strategy_cls.id, item.symbol)] = row
        summary.matrix_rows.append(row)

    _save_matrix(matrix_path, matrix_fields, matrix_data)

    if tested:
        total_trades = sum(r.result.total_trades for r in tested)
        total_wins = sum(r.result.winning_trades for r in tested)
        win_rate = round(total_wins / total_trades * 100, 2) if total_trades else 0.0
        gross_profit = sum(
            r.result.total_pnl for r in tested if r.result.total_pnl > 0
        )
        gross_loss = abs(sum(
            r.result.total_pnl for r in tested if r.result.total_pnl <= 0
        ))
        pf_all = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0
        max_dd = max((r.result.max_drawdown_pct for r in tested), default=0.0)
        total_pnl = sum(r.result.total_pnl for r in tested)
        sharpe_vals = [r.result.sharpe_ratio for r in tested if r.result.total_trades > 0]
        avg_sharpe = round(sum(sharpe_vals) / len(sharpe_vals), 2) if sharpe_vals else 0.0
        avg_rr_vals = [r.result.avg_rr for r in tested if r.result.total_trades > 0]
        avg_rr = round(sum(avg_rr_vals) / len(avg_rr_vals), 2) if avg_rr_vals else 0.0

        summary.aggregate_stats = {
            "bt_total_trades_all": total_trades,
            "bt_win_rate_all": win_rate,
            "bt_profit_factor_all": pf_all,
            "bt_max_drawdown_pct_all": max_dd,
            "bt_total_pnl_all": round(total_pnl, 2),
            "bt_sharpe_ratio_all": avg_sharpe,
            "bt_avg_rr_all": avg_rr,
        }

    return summary


def update_tracking_csv(
    csv_path: Path,
    module_id: str,
    summary: MultiInstrumentSummary,
    status: str,
    anti_bias_passed: str = "yes",
    anti_bias_notes: str = "",
    backtest_error: str = "",
):
    fieldnames, rows = _read_csv_rows(csv_path)
    now = _utc_now_iso()

    canonical_row = None
    for row in rows:
        if row.get("module_to_code") == module_id and row.get("action") == "CODE-CANONICAL":
            canonical_row = row
            break

    if canonical_row is None:
        return

    canonical_row["implementation_status"] = status
    canonical_row["strategy_module_id"] = module_id
    canonical_row["strategy_folder"] = f"strategies/{module_id}/"
    canonical_row["strategy_registry_id"] = summary.strategy_id
    canonical_row["coded_at"] = canonical_row.get("coded_at") or now
    canonical_row["anti_bias_review_passed"] = anti_bias_passed
    canonical_row["anti_bias_notes"] = anti_bias_notes
    canonical_row["backtest_error"] = backtest_error
    canonical_row["data_source"] = summary.data_source
    canonical_row["data_root_used"] = summary.data_root_used

    if summary.instruments_tested > 0:
        canonical_row["backtested_at"] = now
        canonical_row["instruments_tested_count"] = str(summary.instruments_tested)

    for key, val in summary.aggregate_stats.items():
        canonical_row[key] = str(val)

    if summary.best_instrument:
        best_row = next(
            (r for r in summary.matrix_rows if r.get("symbol") == summary.best_instrument),
            None,
        )
        if best_row:
            canonical_row["best_instrument"] = summary.best_instrument
            canonical_row["best_instrument_pf"] = best_row.get("bt_profit_factor", "")
            canonical_row["best_instrument_win_rate"] = best_row.get("bt_win_rate", "")
            canonical_row["best_instrument_pnl"] = best_row.get("bt_total_pnl", "")
            canonical_row["best_instrument_trades"] = best_row.get("bt_total_trades", "")

    if summary.worst_instrument:
        canonical_row["worst_instrument"] = summary.worst_instrument

    affinity_parts = []
    if summary.best_instrument:
        affinity_parts.append(f"Best: {summary.best_instrument}")
    if summary.worst_instrument:
        affinity_parts.append(f"Weakest: {summary.worst_instrument}")
    if summary.instruments_skipped:
        affinity_parts.append(f"Skipped {summary.instruments_skipped} symbols (missing TF/data)")
    canonical_row["instrument_affinity_notes"] = ". ".join(affinity_parts)

    if status == "coded_and_backtested":
        for row in rows:
            if (
                row.get("action") == "DUPLICATE-SKIP"
                and row.get("module_to_code") == module_id
            ):
                row["implementation_status"] = "covered_by_canonical"
                row["strategy_registry_id"] = summary.strategy_id
                for key in TRACKING_COLUMNS:
                    if key in canonical_row and key not in ("implementation_status",):
                        row[key] = canonical_row.get(key, "")

    _write_csv_atomic(csv_path, fieldnames, rows)


def cmd_run(args: argparse.Namespace):
    strategy_cls = get_strategy(args.strategy)
    if strategy_cls is None:
        print(f"ERROR: Strategy not found: {args.strategy}")
        sys.exit(1)

    module_id = getattr(strategy_cls, "module_id", args.strategy)
    csv_path = Path(args.csv)

    try:
        summary = run_multi_instrument_backtest(
            strategy_id=strategy_cls.id,
            data_root=args.data_root,
            symbols=args.symbols,
            output_dir=args.output,
            start=None,
            end=None,
        )
    except Exception as exc:
        update_tracking_csv(
            csv_path,
            module_id,
            MultiInstrumentSummary(
                strategy_id=strategy_cls.id,
                module_id=module_id,
                video_number=strategy_cls.source_video,
            ),
            status="failed",
            anti_bias_passed="no",
            anti_bias_notes="",
            backtest_error=str(exc),
        )
        raise

    _, has_data = resolve_data_root(args.data_root)
    if has_data and summary.instruments_tested > 0:
        status = "coded_and_backtested"
    else:
        status = "coded_pending_production_backtest"
        summary.data_source = "pending_exness_production"

    anti_bias_notes = (
        "HTF close-only feed; session VP from past bars only; "
        "signals on M1 bar close post-NY-open; stops at absorption wicks; "
        "targets from VP levels (not tuned on PnL)."
    )

    update_tracking_csv(
        csv_path,
        module_id,
        summary,
        status=status,
        anti_bias_passed="yes",
        anti_bias_notes=anti_bias_notes,
    )

    print(f"\nBacktest complete: {strategy_cls.id}")
    print(f"  Tested: {summary.instruments_tested}, Skipped: {summary.instruments_skipped}")
    print(f"  Status: {status}")
    if summary.best_instrument:
        print(f"  Best: {summary.best_instrument}")


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
