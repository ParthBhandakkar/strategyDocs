#!/usr/bin/env python3
"""
Audit strategy coverage against strategy_videos_90.csv.

Reports:
  - Total videos / canonical modules / skipped
  - Which canonical modules have Python files
  - Which strategies emit trade signals (coded vs stub)
  - Which strategies have saved backtest results
"""

from __future__ import annotations

import ast
import csv
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "documents" / "video_docs" / "strategy_videos_90.csv"
STRATEGIES_DIR = ROOT / "documents" / "backtester" / "strategies"
RESULTS_DIR = ROOT / "documents" / "backtester" / "results"
AUDIT_OUTPUT = RESULTS_DIR / "strategy_audit.json"

# Canonical module -> preferred strategy file stem (video number)
MODULE_FILE_HINTS: dict[str, str] = {
    "vp_orderflow_absorption": "s001",
    "gold_london_vp_failed_auction": "s004",
    "multi_vp_ict": "s005",
    "htf_fvg_inversion": "s006",
    "vp_failed_auction_generic": "s008",
    "htf_trend_smt_cisd": "s014",
    "hourly_po3_fib": "s017",
    "ifvg_inversion_ladder": "s028",
    "tbv_absorption": "s029",
    "po3_10am_4h": "s031",
    "daily_bias_judas": "s039",
    "one_candle_8am": "s042",
    "london_orb": "s044",
    "session_dol_fib": "s052",
    "range_sweep_mss": "s054",
    "gold_judas_8pm": "s056",
    "continuation_purge": "s062",
    "us30_judas": "s065",
    "mmxm": "s069",
    "4h_swing_liquidity": "s077",
    "forex_session_judas": "s078",
    "osok_1h_po3": "s081",
}


@dataclass
class StrategyAuditRow:
    module_to_code: str
    canonical_video: int
    title: str
    file_exists: bool
    strategy_id: str | None
    emits_signals: bool
    backtested: bool
    status: str


def load_csv_rows() -> list[dict]:
    with CSV_PATH.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def find_strategy_files() -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in STRATEGIES_DIR.glob("s*.py"):
        match = re.match(r"s(\d+)_", path.name)
        if match:
            files[match.group(1).zfill(3)] = path
    return files


def file_emits_signals(path: Path) -> tuple[bool, str | None]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    strategy_id = None
    emits_signal = False

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if not isinstance(child, ast.Assign):
                    continue
                for target in child.targets:
                    if isinstance(target, ast.Name) and target.id == "id":
                        if isinstance(child.value, ast.Constant) and isinstance(child.value.value, str):
                            strategy_id = child.value.value

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "Signal":
                emits_signal = True

    # Stub detection: on_bar that only returns []
    if not emits_signal and "return []" in source and "def on_bar" in source:
        emits_signal = False

    return emits_signal, strategy_id


def list_backtested_ids() -> set[str]:
    if not RESULTS_DIR.exists():
        return set()
    tested: set[str] = set()
    for path in RESULTS_DIR.glob("*.json"):
        if path.name == "strategy_audit.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sid = data.get("config", {}).get("strategy_id")
            if sid:
                tested.add(sid)
        except (json.JSONDecodeError, OSError):
            continue
    return tested


def build_audit() -> dict:
    csv_rows = load_csv_rows()
    files = find_strategy_files()
    backtested = list_backtested_ids()

    canonical_rows = [
        r for r in csv_rows if r.get("action") == "CODE-CANONICAL"
    ]

    modules: list[StrategyAuditRow] = []
    for row in canonical_rows:
        module = row["module_to_code"]
        video = int(row["video_number"])
        hint = MODULE_FILE_HINTS.get(module, f"s{video:03d}")
        hint_key = hint.replace("s", "")
        video_key = f"{video:03d}"
        path = files.get(hint_key) or files.get(video_key)

        file_exists = path is not None
        emits_signals = False
        strategy_id = None
        if path:
            emits_signals, strategy_id = file_emits_signals(path)

        backtested_flag = bool(strategy_id and strategy_id in backtested)

        if not file_exists:
            status = "missing"
        elif not emits_signals:
            status = "stub"
        elif not backtested_flag:
            status = "coded_not_backtested"
        else:
            status = "coded_and_backtested"

        modules.append(
            StrategyAuditRow(
                module_to_code=module,
                canonical_video=video,
                title=row["title"],
                file_exists=file_exists,
                strategy_id=strategy_id,
                emits_signals=emits_signals,
                backtested=backtested_flag,
                status=status,
            )
        )

    coded = [m for m in modules if m.emits_signals]
    backtested_modules = [m for m in modules if m.backtested]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "csv_total_videos": len(csv_rows),
        "csv_backtestable_videos": sum(1 for r in csv_rows if r.get("is_backtestable") == "yes"),
        "csv_skipped_videos": sum(1 for r in csv_rows if r.get("action") == "SKIP"),
        "canonical_modules": len(canonical_rows),
        "files_on_disk": len(files),
        "modules_with_file": sum(1 for m in modules if m.file_exists),
        "modules_emitting_signals": len(coded),
        "modules_backtested": len(backtested_modules),
        "modules_missing": [m.module_to_code for m in modules if m.status == "missing"],
        "modules_stub_only": [m.module_to_code for m in modules if m.status == "stub"],
        "modules_coded_not_backtested": [
            m.module_to_code for m in modules if m.status == "coded_not_backtested"
        ],
        "modules_coded_and_backtested": [
            m.module_to_code for m in modules if m.status == "coded_and_backtested"
        ],
    }

    return {
        "summary": summary,
        "canonical_modules": [asdict(m) for m in modules],
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    audit = build_audit()
    AUDIT_OUTPUT.write_text(json.dumps(audit, indent=2), encoding="utf-8")

    s = audit["summary"]
    print("Strategy Audit")
    print("=" * 50)
    print(f"CSV videos: {s['csv_total_videos']} (backtestable: {s['csv_backtestable_videos']})")
    print(f"Canonical modules: {s['canonical_modules']}")
    print(f"Strategy files on disk: {s['files_on_disk']}")
    print(f"Modules with file: {s['modules_with_file']}")
    print(f"Modules emitting signals: {s['modules_emitting_signals']}")
    print(f"Modules backtested: {s['modules_backtested']}")
    print(f"Missing: {', '.join(s['modules_missing']) or 'none'}")
    print(f"Stub only: {len(s['modules_stub_only'])} modules")
    print(f"Coded not backtested: {len(s['modules_coded_not_backtested'])} modules")
    print(f"\nFull report: {AUDIT_OUTPUT}")


if __name__ == "__main__":
    main()
