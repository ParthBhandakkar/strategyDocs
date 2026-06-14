"""Extract strategy fingerprints from individual video docs and cluster by concept."""
import re
import json
from pathlib import Path

INDIVIDUAL_DIR = Path(__file__).parent / "individual"

# Concept tags for clustering (ordered by specificity)
CONCEPT_PATTERNS = [
    ("orderflow_absorption", r"absorption|footprint|orderflow|order flow|delta|big trades|deep charts"),
    ("volume_profile", r"volume profile|vah|val|poc|vwap|auction|fixed range"),
    ("tbv_time_based_volume", r"time.?based volume|tbv|reassessment"),
    ("po3_10am", r"10\s*:?\s*00\s*am|10am po3|10 am po3"),
    ("po3_9am", r"9\s*:?\s*00\s*am|9am candle|9 am candle"),
    ("po3_daily", r"power of three|po3|amd|accumulation.*manipulation.*distribution|silver bullet"),
    ("judas_swing", r"judas swing|judas"),
    ("midas_model", r"midas model|midas"),
    ("mmxm", r"market maker model|mmxm"),
    ("one_candle_8am", r"8\s*:?\s*00\s*am|8am candle|one.?candle|hourly range|1-candle hourly"),
    ("one_candle_8pm", r"8\s*:?\s*00\s*pm|8pm|asian session gold"),
    ("orb_lazy_liquidity", r"opening range|orb|lazy liquidity|mechanical orb"),
    ("liquidity_sweep_mss", r"liquidity sweep|sweep.*liquidity|sweep.*high|sweep.*low"),
    ("inversion_fvg", r"inversion.*fvg|inverse fvg|ifvg|iFVG|inversion fair value"),
    ("breaker_block", r"breaker block|breaker"),
    ("order_block", r"order block|\bob\b"),
    ("fvg_entry", r"fair value gap|\bfvg\b"),
    ("daily_bias", r"daily bias|2-day|mechanical.*bias"),
    ("smt_divergence", r"smt|divergence"),
    ("4h_pattern", r"4.?hour|4h pattern|4h core"),
    ("1h_1m_pattern", r"1h.*1m|1-hour.*1-minute"),
    ("continuation_purge", r"continuation purge|trend continuation"),
    ("draw_on_liquidity", r"draw on liquidity|dol"),
    ("structure_liquidity", r"structure.*liquidity|liquidity range"),
    ("crypto_funding", r"crypto|bitcoin|funding rate|100x"),
    ("gbpusd_range", r"gbpusd|gbp/usd"),
    ("backtesting_tutorial", r"backtest"),
    ("mindset_only", r"mindfulness|failing as a trader|quit trading|life of a day trader"),
]

ENTRY_PATTERNS = [
    ("inversion_fvg", r"inversion.*fvg|inverse fvg|ifvg"),
    ("breaker", r"breaker"),
    ("order_block", r"order block"),
    ("fvg", r"fair value gap|\bfvg\b"),
    ("mss", r"market structure shift|mss|cisd|structure shift"),
    ("cisd", r"cisd|change in state of delivery"),
    ("limit_retest", r"limit.*retest|retest"),
    ("market_on_close", r"close.*inside|body close|close back"),
]

RANGE_PATTERNS = [
    ("8am_1h", r"8\s*:?\s*00\s*am"),
    ("9am_1h", r"9\s*:?\s*00\s*am"),
    ("10am", r"10\s*:?\s*00\s*am"),
    ("8pm_gold", r"8\s*:?\s*00\s*pm"),
    ("hourly_any", r"hourly range|1-hour candle|1h candle"),
    ("4h", r"4.?hour|4h"),
    ("15m", r"15.?minute|15m"),
    ("session_orb", r"opening range|session open|new york open|9:30"),
]


def read_doc(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_title(content: str) -> str:
    m = re.search(r"Strategy/Topic Name:\s*(.+)", content)
    if m:
        return m.group(1).strip()
    first = content.strip().split("\n")[0].strip()
    return re.sub(r"^\d+\.\s*", "", first)


def extract_source(content: str) -> str:
    m = re.search(r'Source:.*?\("([^"]+)"\)', content)
    return m.group(1) if m else ""


def match_tags(text: str, patterns: list) -> list[str]:
    lower = text.lower()
    return [name for name, pat in patterns if re.search(pat, lower, re.I)]


def extract_steps_summary(content: str) -> str:
    """Pull step section for fingerprinting."""
    m = re.search(
        r"(Step-by-Step|Step \d|Overview)(.+?)(Key Rules|Trade Examples|Example 1|$)",
        content,
        re.S | re.I,
    )
    return m.group(0)[:3000] if m else content[:3000]


def classify_strategy(content: str) -> dict:
    full = content.lower()
    steps = extract_steps_summary(content).lower()
    combined = full

    concepts = match_tags(combined, CONCEPT_PATTERNS)
    entries = match_tags(combined, ENTRY_PATTERNS)
    ranges = match_tags(combined, RANGE_PATTERNS)

    # Determine primary family
    family = "other"
    if "backtesting_tutorial" in concepts:
        family = "non_strategy_tutorial"
    elif "mindset_only" in concepts and len([c for c in concepts if c not in ("mindset_only",)]) < 2:
        family = "non_strategy_mindset"
    elif "orderflow_absorption" in concepts and "volume_profile" in concepts:
        family = "orderflow_volume_profile"
    elif "tbv_time_based_volume" in concepts:
        family = "time_based_volume"
    elif "midas_model" in concepts:
        family = "midas_model"
    elif "po3_10am" in concepts or ("po3_daily" in concepts and "10am" in ranges):
        family = "po3_10am_session"
    elif "po3_9am" in concepts:
        family = "po3_9am_candle"
    elif "po3_daily" in concepts or "advanced_amd" in full:
        family = "po3_amd_daily"
    elif "judas_swing" in concepts:
        family = "judas_swing"
    elif "one_candle_8pm" in concepts:
        family = "gold_8pm_one_candle"
    elif "one_candle_8am" in concepts or "8am_1h" in ranges:
        family = "one_candle_8am_range"
    elif "orb_lazy_liquidity" in concepts:
        family = "orb_lazy_liquidity"
    elif "mmxm" in concepts:
        family = "mmxm"
    elif "4h_pattern" in concepts or ("4h" in ranges and "liquidity_sweep_mss" in concepts):
        family = "4h_liquidity_mss"
    elif "1h_1m_pattern" in concepts:
        family = "1h_1m_pattern"
    elif "inversion_fvg" in concepts or "inversion_fvg" in entries:
        family = "liquidity_sweep_inversion_fvg"
    elif "liquidity_sweep_mss" in concepts:
        family = "liquidity_sweep_mss_entry"
    elif "daily_bias" in concepts:
        family = "daily_bias_framework"
    elif "smt_divergence" in concepts:
        family = "smt_divergence"
    elif "continuation_purge" in concepts:
        family = "continuation_purge"
    elif "volume_profile" in concepts:
        family = "volume_profile"
    elif "crypto_funding" in concepts:
        family = "crypto_strategy"
    elif "gbpusd_range" in concepts:
        family = "gbpusd_range"
    elif "structure_liquidity" in concepts:
        family = "structure_liquidity"

    # Entry signature for sub-clustering
    entry_sig = "+".join(sorted(set(entries))) or "unspecified"
    range_sig = "+".join(sorted(set(ranges))) or "unspecified"

    return {
        "concepts": concepts,
        "entries": entries,
        "ranges": ranges,
        "family": family,
        "entry_sig": entry_sig,
        "range_sig": range_sig,
    }


def main():
    files = sorted(
        INDIVIDUAL_DIR.glob("video_*.md"),
        key=lambda p: int(re.search(r"video_(\d+)", p.name).group(1)),
    )
    assert len(files) == 90, f"Expected 90 files, got {len(files)}"

    records = []
    for f in files:
        vid = int(re.search(r"video_(\d+)", f.name).group(1))
        content = read_doc(f)
        cls = classify_strategy(content)
        records.append(
            {
                "video": vid,
                "file": f.name,
                "title": extract_title(content),
                "source": extract_source(content),
                **cls,
            }
        )

    # Cluster by family + entry_sig + range_sig (concept-level dedup key)
    clusters: dict[str, list] = {}
    for r in records:
        if r["family"].startswith("non_strategy"):
            key = r["family"]
        else:
            key = f"{r['family']}|{r['range_sig']}|{r['entry_sig']}"
        clusters.setdefault(key, []).append(r)

    # Merge clusters with same family where entry/range only differ slightly
    family_groups: dict[str, list] = {}
    for r in records:
        if r["family"].startswith("non_strategy"):
            family_groups.setdefault(r["family"], []).append(r)
        else:
            family_groups.setdefault(r["family"], []).append(r)

    out = {
        "total_videos": len(records),
        "unique_families": len([f for f in family_groups if not f.startswith("non_strategy")]),
        "non_strategy_count": sum(
            len(v) for k, v in family_groups.items() if k.startswith("non_strategy")
        ),
        "family_groups": {
            k: [{"video": r["video"], "title": r["title"], "source": r["source"]} for r in v]
            for k, v in sorted(family_groups.items())
        },
        "detailed_clusters": {
            k: [{"video": r["video"], "title": r["title"]} for r in v]
            for k, v in sorted(clusters.items(), key=lambda x: (-len(x[1]), x[0]))
        },
        "records": records,
    }

    out_path = Path(__file__).parent / "strategy_dedup_analysis.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Analyzed {len(records)} videos -> {len(family_groups)} family groups")
    print(f"Detailed clusters: {len(clusters)}")
    for fam, items in sorted(family_groups.items(), key=lambda x: -len(x[1])):
        print(f"  {fam}: {len(items)} videos -> {[i['video'] for i in items]}")


if __name__ == "__main__":
    main()
