#!/usr/bin/env python3
"""
Audit strategy coverage against strategy_videos_90.csv canonical modules.

Reports:
- 22 unique canonical modules from CSV
- Strategy files present (by canonical video number)
- Implemented strategies (on_bar emits Signal)
- Backtest result files saved under documents/backtester/results/
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "documents"
CSV_PATH = DOCS / "video_docs" / "strategy_videos_90.csv"
STRAT_DIR = DOCS / "backtester" / "strategies"
RESULTS_DIR = DOCS / "backtester" / "results"


def load_canonical() -> dict[str, dict]:
    canonical = {}
    with CSV_PATH.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["action"] == "CODE-CANONICAL":
                canonical[row["module_to_code"]] = {
                    "video": int(row["video_number"]),
                    "cluster": row["cluster_id"],
                    "title": row["title"],
                }
    return canonical


def video_to_strategy_file() -> dict[int, str]:
    mapping = {}
    for path in sorted(STRAT_DIR.glob("s*.py")):
        match = re.match(r"s(\d+)_", path.name)
        if match:
            mapping[int(match.group(1))] = path.name
    return mapping


def implemented_videos() -> set[int]:
    done: set[int] = set()
    for path in STRAT_DIR.glob("s*.py"):
        text = path.read_text()
        if "def on_bar" not in text or "Signal(" not in text:
            continue
        body = text.split("def on_bar", 1)[1]
        if "Signal(" in body:
            match = re.match(r"s(\d+)_", path.name)
            if match:
                done.add(int(match.group(1)))
    return done


def backtested_modules() -> dict[str, str]:
    if not RESULTS_DIR.exists():
        return {}
    out = {}
    for path in sorted(RESULTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            sid = data.get("strategy_id") or data.get("config", {}).get("strategy_id")
            if sid:
                out[sid] = path.name
        except (json.JSONDecodeError, OSError):
            continue
    return out


def main() -> int:
    canonical = load_canonical()
    files = video_to_strategy_file()
    implemented = implemented_videos()
    results = backtested_modules()

    coded = []
    impl_mods = []
    missing_files = []
    backtested = []

    print("Strategy audit — canonical modules from strategy_videos_90.csv\n")
    print(f"{'Video':>5}  {'Module':<28}  {'File':<36}  {'Coded':^6}  {'Impl':^5}  {'BT':^4}")
    print("-" * 95)

    for mod, info in sorted(canonical.items(), key=lambda x: x[1]["video"]):
        v = info["video"]
        fname = files.get(v, "")
        has_file = bool(fname)
        is_impl = v in implemented
        sid_guess = f"s{v:03d}_" if has_file else ""
        bt = any(sid.startswith(sid_guess) for sid in results) if sid_guess else False

        if has_file:
            coded.append(mod)
        else:
            missing_files.append(mod)
        if is_impl:
            impl_mods.append(mod)
        if bt:
            backtested.append(mod)

        print(
            f"V{v:02d}   {mod:<28}  {(fname or '—'):<36}  "
            f"{'yes' if has_file else 'no':^6}  {'yes' if is_impl else 'no':^5}  {'yes' if bt else 'no':^4}"
        )

    print()
    print("Summary")
    print(f"  Canonical modules (unique):     {len(canonical)}")
    print(f"  Strategy files present:         {len(coded)} / {len(canonical)}")
    print(f"  Implemented (emit trades):      {len(impl_mods)} / {len(canonical)}")
    print(f"  Backtest results saved:         {len(backtested)} / {len(canonical)}")
    if missing_files:
        print(f"  Missing files:                  {', '.join(missing_files)}")
    if results:
        print(f"  Result files:                   {', '.join(sorted(results.values()))}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
