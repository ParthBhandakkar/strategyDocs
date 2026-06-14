"""Extract structured summaries from all 90 video markdown files."""
import json
import re
from pathlib import Path

INDIVIDUAL_DIR = Path(__file__).parent / "individual"


def extract(path: Path, content: str) -> dict:
    vid = int(re.search(r"video_(\d+)", path.name).group(1))
    title_m = re.search(r"Strategy/Topic Name:\s*(.+)", content)
    title = title_m.group(1).strip() if title_m else path.stem
    src_m = re.search(r'Source:.*?\("([^"]+)"\)', content)
    source = src_m.group(1) if src_m else ""
    overview_m = re.search(
        r"Overview\s*\n+(.+?)(?=\nStep|\nKey Rules|\nTrade Examples|\nRisk Management|\nSummary)",
        content,
        re.S,
    )
    overview = overview_m.group(1).strip()[:600] if overview_m else ""

    sessions = []
    for pat, label in [
        (r"8\s*:?\s*00\s*am", "8AM NY"),
        (r"9\s*:?\s*00\s*am", "9AM NY"),
        (r"10\s*:?\s*00\s*am", "10AM NY"),
        (r"8\s*:?\s*00\s*pm", "8PM NY"),
        (r"09:30|9:30", "NY open 9:30"),
        (r"14:00|2:00\s*pm", "NY cutoff 2PM"),
        (r"silver bullet", "Silver Bullet window"),
        (r"london", "London session"),
        (r"asia", "Asia session"),
    ]:
        if re.search(pat, content, re.I):
            sessions.append(label)

    assets = []
    for pat, label in [
        (r"\bNQ\b|nasdaq", "NQ"),
        (r"\bES\b|s&p 500", "ES"),
        (r"gold|xau", "Gold"),
        (r"silver", "Silver"),
        (r"us30|dow", "US30"),
        (r"gbpusd|gbp/usd", "GBPUSD"),
        (r"crypto|bitcoin|btc", "Crypto"),
    ]:
        if re.search(pat, content, re.I):
            assets.append(label)

    entries = []
    for pat, label in [
        (r"inversion.*fvg|inverse fvg|ifvg", "inversion FVG"),
        (r"liquidity sweep|sweep.*high|sweep.*low", "liquidity sweep"),
        (r"market structure shift|\bmss\b", "MSS"),
        (r"\bcisd\b|change in state of delivery", "CISD"),
        (r"breaker", "breaker"),
        (r"order block", "order block"),
        (r"fair value gap|\bfvg\b", "FVG"),
        (r"volume profile|vah|val|poc|vwap", "volume profile"),
        (r"judas swing", "Judas swing"),
        (r"power of three|po3|\bamd\b", "PO3/AMD"),
        (r"midas model", "Midas model"),
        (r"market maker model|mmxm", "MMXM"),
        (r"continuation purge", "continuation purge"),
        (r"absorption|orderflow|footprint", "orderflow absorption"),
        (r"daily bias", "daily bias"),
        (r"smt|divergence", "SMT divergence"),
        (r"opening range|\borb\b", "ORB"),
        (r"funding rate", "funding rate"),
        (r"draw on liquidity|\bdol\b", "draw on liquidity"),
    ]:
        if re.search(pat, content, re.I):
            entries.append(label)

    # HTF/LTF from step sections
    htf = set()
    ltf = set()
    for m in re.finditer(
        r"Timeframe:\s*([^\n]+)", content, re.I
    ):
        tf_line = m.group(1).lower()
        if any(x in tf_line for x in ["4-hour", "4 hour", "4h", "daily", "1-hour", "1 hour", "1h", "hourly"]):
            htf.add(m.group(1).strip())
        if any(x in tf_line for x in ["1-minute", "1 minute", "1m", "5-minute", "5 minute", "5m", "15-minute", "15m"]):
            ltf.add(m.group(1).strip())

    steps = len(re.findall(r"^Step \d", content, re.M))

    non_strategy = False
    ns_reason = ""
    lower = content.lower()
    if re.search(r"backtest(ing)?\s+tutorial|increase your trading skills.*backtest", lower):
        non_strategy, ns_reason = True, "backtesting tutorial"
    elif re.search(
        r"become a profitable trader in one day|please quit trading|"
        r"failing as a trader|mindfulness for traders|"
        r"give me 6 minutes of your life",
        lower,
    ):
        non_strategy, ns_reason = True, "mindset"
    elif re.search(r"mindfulness|meditat|quit trading|failing as a trader", lower) and steps < 3:
        non_strategy, ns_reason = True, "mindset"
    elif re.search(r"life of a day trader", lower):
        non_strategy, ns_reason = True, "lifestyle vlog"
    elif re.search(r"orderflow boot camp lesson", lower):
        non_strategy, ns_reason = True, "educational lesson (orderflow boot camp)"
    elif steps < 2 and re.search(r"trade breakdown|full breakdown", lower):
        non_strategy, ns_reason = True, "trade breakdown only"
    elif steps < 2 and re.search(r"live (day )?trading", lower):
        non_strategy, ns_reason = True, "live trade demo"

    # range/candle refs
    ranges = []
    for pat, label in [
        (r"8\s*:?\s*00\s*am.*candle|8am candle", "8AM 1H candle"),
        (r"9\s*:?\s*00\s*am.*candle|9am candle", "9AM 1H candle"),
        (r"10\s*:?\s*00\s*am|10am po3", "10AM PO3"),
        (r"8\s*:?\s*00\s*pm", "8PM candle/session"),
        (r"hourly range|1-candle hourly|one.?candle", "hourly one-candle range"),
        (r"4.?hour|4h", "4H structure"),
        (r"opening range", "opening range"),
        (r"session high|session low|daily high|daily low", "session/daily liquidity"),
        (r"fixed range volume profile", "fixed-range VP"),
        (r"liquidity range", "liquidity range"),
    ]:
        if re.search(pat, content, re.I):
            ranges.append(label)

    return {
        "video": vid,
        "title": title,
        "source": source,
        "overview": overview,
        "steps": steps,
        "non_strategy": non_strategy,
        "ns_reason": ns_reason,
        "sessions": list(dict.fromkeys(sessions)),
        "assets": list(dict.fromkeys(assets)),
        "entries": list(dict.fromkeys(entries)),
        "ranges": list(dict.fromkeys(ranges)),
        "htf": sorted(htf),
        "ltf": sorted(ltf),
    }


def main():
    files = sorted(
        INDIVIDUAL_DIR.glob("video_*.md"),
        key=lambda p: int(re.search(r"video_(\d+)", p.name).group(1)),
    )
    records = [extract(f, f.read_text(encoding="utf-8")) for f in files]
    out = Path(__file__).parent / "extract_all.json"
    out.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Wrote {len(records)} records to {out}")
    for r in records:
        strat = "NON-STRAT" if r["non_strategy"] else "STRATEGY"
        print(
            f"{r['video']:02d} [{strat}] steps={r['steps']} | "
            f"{r['title'][:55]}"
        )


if __name__ == "__main__":
    main()
