#!/usr/bin/env python3
"""Enrich strategy_videos_90.csv with coding and backtest status per video."""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRAT_DIR = ROOT / "backtester" / "strategies"
CSV_PATH = ROOT / "video_docs" / "strategy_videos_90.csv"

FULLY_CODED = {
    "s003_liquidity_sweep_1m",
    "s004_volume_profile_auction",
    "s006_fractal_inversion_orderflow",
    "s012_8am_candle",
    "s013_800am_candle",
    "s026_inverse_fvg_scalp",
    "s027_po3_silver_bullet",
    "s038_4h_smt_divergence",
    "s044_lazy_liquidity_orb",
}

PARTIAL = {
    "s001_orderflow_volume_profile",
    "s005_macro_volume_profile",
    "s015_orderflow_bootcamp",
    "s017_1h_pattern",
    "s018_only_gold_strategy",
    "s022_simplified_ict_amd",
    "s029_time_based_volume_tbv",
    "s031_10am_po3",
}

# Videos that share a coded file (duplicate_of or cluster canonical)
VIDEO_TO_FILE_OVERRIDE = {
    54: "s003_liquidity_sweep_1m",  # Q cluster; 1M implementation exists as s003
}


def strategy_file_for_video(video_num: int) -> str | None:
    if video_num in VIDEO_TO_FILE_OVERRIDE:
        return VIDEO_TO_FILE_OVERRIDE[video_num]
    matches = list(STRAT_DIR.glob(f"s{video_num:03d}_*.py"))
    if matches:
        return matches[0].stem
    return None


def parse_backtest_summary(text: str) -> dict | None:
    m = re.search(
        r'BACKTEST RESULTS \(local Exness CSV[^\n]*\n(.*?)"""',
        text,
        re.DOTALL,
    )
    if not m:
        return None
    parsed = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or ": Trades:" not in line and ": ERROR:" not in line:
            continue
        if ": ERROR:" in line:
            sym = line.split(":", 1)[0].strip()
            parsed.append({"symbol": sym, "error": True})
            continue
        sym = line.split(":", 1)[0].strip()
        stats = re.search(
            r"Trades: (\d+) \| Win rate: ([\d.]+)% \| PF: ([\d.inf]+) \| PnL: \$([-\d.]+)",
            line,
        )
        if stats:
            pf_raw = stats.group(3)
            parsed.append({
                "symbol": sym,
                "trades": int(stats.group(1)),
                "win_rate": float(stats.group(2)),
                "pf": float("inf") if pf_raw == "inf" else float(pf_raw),
                "pnl": float(stats.group(4)),
            })
    return {"rows": parsed} if parsed else None


def summarize_backtest(data: dict | None, code_status: str) -> str:
    if code_status == "no_file":
        return "No strategy file"
    if code_status == "stub":
        return "Stub only (on_bar returns []); not backtestable for trades"
    if code_status == "partial":
        return "Partial code (no Signal emission); backtest produces 0 trades"
    if not data:
        return "Fully coded but not yet backtested on local CSV"
    rows = [r for r in data["rows"] if not r.get("error") and r.get("trades", 0) > 0]
    pair_count = len(data["rows"])
    if not rows:
        return f"Backtested {pair_count} pairs Jan-Jun 2024; 0 trades on all symbols"
    total_trades = sum(r["trades"] for r in rows)
    profitable = [r for r in rows if r["pnl"] > 0]
    best_pf = max(rows, key=lambda r: r["pf"] if r["pf"] != float("inf") else 999)
    best_pnl = max(rows, key=lambda r: r["pnl"])
    return (
        f"Backtested {pair_count} pairs Jan-Jun 2024 | {len(rows)} symbols with trades | "
        f"total {total_trades} trades | profitable symbols: {len(profitable)} | "
        f"best PF {best_pf['symbol']} {best_pf['pf']} | best PnL {best_pnl['symbol']} ${best_pnl['pnl']:.2f}"
    )


def remaining_work(
    is_backtestable: str,
    content_type: str,
    action: str,
    code_status: str,
    coded_file: str | None,
    backtest_summary: str,
) -> str:
    if is_backtestable != "yes" or content_type != "strategy":
        return "N/A — not a backtestable strategy video"
    if action == "SKIP" and "mindset" in content_type or content_type in (
        "non_strategy_tutorial",
        "non_strategy_mindset",
        "non_strategy_demo",
    ):
        return "N/A — skip per classification"
    if code_status == "no_file":
        return "Implement strategy Python module and add to backtester registry"
    if code_status == "stub":
        return "Implement on_bar logic + Signal emission; then backtest all pairs"
    if code_status == "partial":
        return "Add trade Signal emission; re-run run_backtests.py on all pairs"
    if "best PF" in backtest_summary and "profitable symbols: 0" in backtest_summary:
        return "Coded and backtested; tune parameters or review edge (unprofitable on Jan-Jun 2024)"
    if code_status == "fully_coded":
        return "Coded and backtested on local Exness data (Jan-Jun 2024); optional tuning"
    return "Review and complete"


def load_strategy_meta() -> dict[str, dict]:
    meta = {}
    for path in STRAT_DIR.glob("s*.py"):
        text = path.read_text(encoding="utf-8")
        sid = path.stem
        if sid in FULLY_CODED:
            status = "fully_coded"
        elif sid in PARTIAL:
            status = "partial"
        elif "Signal(" in text:
            status = "fully_coded"
        elif re.search(r"def on_bar\([^)]*\)[^:]*:\s*\n\s*return \[\]", text):
            status = "stub"
        else:
            status = "stub"
        meta[sid] = {
            "code_status": status,
            "backtest": parse_backtest_summary(text),
        }
    return meta


def main():
    strat_meta = load_strategy_meta()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        new_cols = [
            "coded_strategy_file",
            "code_status",
            "backtest_status",
            "backtest_summary",
            "remaining_work",
        ]
        for col in new_cols:
            if col not in fieldnames:
                fieldnames.append(col)
        rows = list(reader)

    for row in rows:
        try:
            vid = int(row["video_number"])
        except (KeyError, ValueError):
            continue

        coded = strategy_file_for_video(vid)
        if coded and coded in strat_meta:
            code_status = strat_meta[coded]["code_status"]
            bt_data = strat_meta[coded]["backtest"]
        elif coded:
            code_status = "stub"
            bt_data = None
        else:
            code_status = "no_file"
            bt_data = None

        if row.get("is_backtestable") != "yes" or row.get("content_type") != "strategy":
            bt_status = "not_applicable"
        elif code_status == "fully_coded" and bt_data:
            bt_status = "backtested_all_pairs"
        elif code_status == "fully_coded":
            bt_status = "pending_backtest"
        elif code_status in ("partial", "stub"):
            bt_status = "not_tradeable_yet"
        else:
            bt_status = "not_coded"

        summary = summarize_backtest(bt_data, code_status)
        row["coded_strategy_file"] = coded or ""
        row["code_status"] = code_status
        row["backtest_status"] = bt_status
        row["backtest_summary"] = summary
        row["remaining_work"] = remaining_work(
            row.get("is_backtestable", ""),
            row.get("content_type", ""),
            row.get("action", ""),
            code_status,
            coded,
            summary,
        )

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {CSV_PATH} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
