#!/usr/bin/env python3
"""
Audit canonical strategy modules from strategy_videos_90.csv against
implemented strategy files and saved backtest results.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKTESTER = ROOT / "documents" / "backtester"
STRATEGIES_DIR = BACKTESTER / "strategies"
RESULTS_DIR = BACKTESTER / "results"
CSV_PATH = ROOT / "documents" / "video_docs" / "strategy_videos_90.csv"

# Canonical video number per unique module (from STRATEGY_DEDUP_FINDINGS.md)
CANONICAL_VIDEO: dict[str, int] = {
    "vp_orderflow_absorption": 1,
    "gold_london_vp_failed_auction": 4,
    "multi_vp_ict": 5,
    "htf_fvg_inversion": 6,
    "vp_failed_auction_generic": 8,
    "htf_trend_smt_cisd": 13,
    "hourly_po3_fib": 17,
    "ifvg_inversion_ladder": 28,
    "tbv_absorption": 29,
    "po3_10am_4h": 31,
    "daily_bias_judas": 39,
    "one_candle_8am": 42,
    "london_orb": 44,
    "session_dol_fib": 52,
    "range_sweep_mss": 54,
    "gold_judas_8pm": 56,
    "continuation_purge": 62,
    "us30_judas": 65,
    "mmxm": 69,
    "4h_swing_liquidity": 77,
    "forex_session_judas": 78,
    "osok_1h_po3": 81,
}


def find_strategy_file(video_num: int) -> Path | None:
    pattern = f"s{video_num:03d}_*.py"
    matches = sorted(STRATEGIES_DIR.glob(pattern))
    return matches[0] if matches else None


def extract_strategy_id(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^\s*id\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return match.group(1) if match else None


def is_implemented(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "def on_bar" not in text:
        return False
    # Stub strategies only `return []` from on_bar without emitting signals.
    return bool(
        re.search(r"return\s+\[\s*Signal\s*\(", text)
        or re.search(r"return\s+\[\s*signal\s*\]", text)
    )


def has_backtest_result(strategy_id: str) -> bool:
    return (RESULTS_DIR / f"{strategy_id}.json").exists()


def load_csv_rows() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def run_audit() -> dict:
    rows = load_csv_rows()
    canonical_rows = [r for r in rows if r.get("action") == "CODE-CANONICAL"]

    modules: list[dict] = []
    for row in canonical_rows:
        module = row["module_to_code"]
        video = CANONICAL_VIDEO.get(module, int(row["video_number"]))
        path = find_strategy_file(video)
        strategy_id = extract_strategy_id(path) if path else None
        coded = path is not None
        implemented = is_implemented(path) if path else False
        backtested = has_backtest_result(strategy_id) if strategy_id else False

        modules.append(
            {
                "module": module,
                "cluster": row.get("cluster_id", ""),
                "canonical_video": video,
                "title": row.get("title", ""),
                "strategy_file": path.name if path else None,
                "strategy_id": strategy_id,
                "coded": coded,
                "implemented": implemented,
                "backtested": backtested,
            }
        )

    total_videos = len(rows)
    backtestable = sum(1 for r in rows if r.get("is_backtestable") == "yes")
    unique_modules = len(canonical_rows)

    coded_count = sum(1 for m in modules if m["coded"])
    implemented_count = sum(1 for m in modules if m["implemented"])
    backtested_count = sum(1 for m in modules if m["backtested"])

    return {
        "summary": {
            "total_csv_videos": total_videos,
            "backtestable_videos": backtestable,
            "unique_canonical_modules": unique_modules,
            "coded_modules": coded_count,
            "implemented_modules": implemented_count,
            "backtested_modules": backtested_count,
            "missing_module_files": unique_modules - coded_count,
            "stub_only_modules": coded_count - implemented_count,
            "not_backtested_implemented": implemented_count - backtested_count,
        },
        "modules": modules,
        "missing_files": [m for m in modules if not m["coded"]],
        "stubs": [m for m in modules if m["coded"] and not m["implemented"]],
        "needs_backtest": [m for m in modules if m["implemented"] and not m["backtested"]],
    }


def print_report(report: dict) -> None:
    summary = report["summary"]
    print("=" * 72)
    print("STRATEGY AUDIT — strategy_videos_90.csv")
    print("=" * 72)
    print(f"Total videos in CSV:           {summary['total_csv_videos']}")
    print(f"Backtestable videos:           {summary['backtestable_videos']}")
    print(f"Unique canonical modules:      {summary['unique_canonical_modules']}")
    print(f"Coded (file exists):           {summary['coded_modules']}")
    print(f"Implemented (emits signals):   {summary['implemented_modules']}")
    print(f"Backtested (results saved):    {summary['backtested_modules']}")
    print()

    print("CANONICAL MODULE STATUS")
    print("-" * 72)
    print(f"{'Module':<28} {'Video':>5} {'Coded':>6} {'Impl':>6} {'BT':>4}  Strategy ID")
    print("-" * 72)
    for m in report["modules"]:
        print(
            f"{m['module']:<28} {m['canonical_video']:>5} "
            f"{'yes' if m['coded'] else 'no':>6} "
            f"{'yes' if m['implemented'] else 'no':>6} "
            f"{'yes' if m['backtested'] else 'no':>4}  "
            f"{m['strategy_id'] or '-'}"
        )

    if report["missing_files"]:
        print()
        print("MISSING MODULE FILES (no s{video}_*.py)")
        for m in report["missing_files"]:
            print(f"  - {m['module']} (video {m['canonical_video']}: {m['title']})")

    if report["stubs"]:
        print()
        print("STUB ONLY (file exists, no Signal emission)")
        for m in report["stubs"]:
            print(f"  - {m['module']} -> {m['strategy_file']}")

    if report["needs_backtest"]:
        print()
        print("IMPLEMENTED BUT NOT BACKTESTED")
        for m in report["needs_backtest"]:
            print(f"  - {m['module']} -> {m['strategy_id']}")


def main() -> int:
    if not CSV_PATH.exists():
        print(f"CSV not found: {CSV_PATH}", file=sys.stderr)
        return 1

    report = run_audit()
    print_report(report)

    out_path = RESULTS_DIR / "strategy_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print()
    print(f"Audit JSON saved to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
