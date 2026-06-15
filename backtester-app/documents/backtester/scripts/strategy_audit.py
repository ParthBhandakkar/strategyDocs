#!/usr/bin/env python3
"""
Compare strategy_videos_90.csv against coded strategies and saved backtest results.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

BACKTESTER_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = BACKTESTER_ROOT.parent / "video_docs" / "strategy_videos_90.csv"
STRATEGIES_DIR = BACKTESTER_ROOT / "strategies"
RESULTS_DIR = BACKTESTER_ROOT / "backtest_results"
STATUS_PATH = BACKTESTER_ROOT / "strategy_status.json"


def _has_trade_logic(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    return "Signal(" in text and "return [" in text


def _coded_video_numbers() -> dict[int, dict]:
    coded: dict[int, dict] = {}
    for path in sorted(STRATEGIES_DIR.glob("s*.py")):
        match = re.match(r"s(\d{3})_", path.name)
        if not match:
            continue
        video_num = int(match.group(1))
        coded[video_num] = {
            "file": path.name,
            "strategy_id": _extract_strategy_id(path),
            "has_trade_logic": _has_trade_logic(path),
        }
    return coded


def _extract_strategy_id(path: Path) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("id = "):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _backtested_strategy_ids() -> set[str]:
    if not RESULTS_DIR.exists():
        return set()
    tested: set[str] = set()
    for path in RESULTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sid = data.get("config", {}).get("strategy_id")
            if sid:
                tested.add(sid)
        except (json.JSONDecodeError, OSError):
            continue
    return tested


def run_audit() -> dict:
    coded = _coded_video_numbers()
    backtested_ids = _backtested_strategy_ids()

    rows = []
    with CSV_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            video_num = int(row["video_number"])
            code_info = coded.get(video_num)
            strategy_id = code_info["strategy_id"] if code_info else None
            rows.append(
                {
                    "video_number": video_num,
                    "title": row["title"],
                    "action": row["action"],
                    "module_to_code": row["module_to_code"] or None,
                    "is_backtestable": row["is_backtestable"] == "yes",
                    "coded": code_info is not None,
                    "strategy_file": code_info["file"] if code_info else None,
                    "strategy_id": strategy_id,
                    "has_trade_logic": code_info["has_trade_logic"] if code_info else False,
                    "backtested": strategy_id in backtested_ids if strategy_id else False,
                }
            )

    backtestable = [r for r in rows if r["is_backtestable"]]
    canonical = [r for r in rows if r["action"] == "CODE-CANONICAL"]
    coded_backtestable = [r for r in backtestable if r["coded"]]
    logic_backtestable = [r for r in backtestable if r["has_trade_logic"]]
    backtested = [r for r in backtestable if r["backtested"]]

    uncoded_canonical = [r for r in canonical if not r["coded"]]
    uncoded_backtestable = [r for r in backtestable if not r["coded"]]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "csv_total_videos": len(rows),
        "backtestable_videos": len(backtestable),
        "canonical_modules": len(canonical),
        "coded_files": len(coded),
        "coded_backtestable_videos": len(coded_backtestable),
        "with_trade_logic": len(logic_backtestable),
        "backtested_with_saved_results": len(backtested),
        "uncoded_canonical_modules": len(uncoded_canonical),
        "uncoded_backtestable_videos": len(uncoded_backtestable),
    }

    report = {
        "summary": summary,
        "uncoded_canonical": uncoded_canonical,
        "uncoded_backtestable": uncoded_backtestable,
        "strategies": rows,
    }

    STATUS_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    report = run_audit()
    s = report["summary"]
    print("Strategy Audit Summary")
    print("=" * 40)
    print(f"CSV videos: {s['csv_total_videos']}")
    print(f"Backtestable: {s['backtestable_videos']}")
    print(f"Canonical modules: {s['canonical_modules']}")
    print(f"Coded (file exists): {s['coded_files']}")
    print(f"Coded backtestable videos: {s['coded_backtestable_videos']}")
    print(f"With trade logic (Signal): {s['with_trade_logic']}")
    print(f"Backtested (saved results): {s['backtested_with_saved_results']}")
    print(f"Uncoded canonical modules: {s['uncoded_canonical_modules']}")
    print(f"\nStatus written to {STATUS_PATH}")


if __name__ == "__main__":
    main()
