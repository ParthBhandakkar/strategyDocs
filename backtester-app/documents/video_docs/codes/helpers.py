"""
Shared helper module for all trading strategies - written from scratch.
Provides CSV loading, indicator functions, volume profile, and JSON output.
"""

from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional
import csv
import json
import os


# ───────────────────────────── CSV LOADING ─────────────────────────────

def load_csv(filepath: str) -> list[dict]:
    """Load OHLCV CSV with columns: Date,Time,Open,High,Low,Close,Volume.
    Returns list of dicts with keys: time, open, high, low, close, volume
    """
    bars = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt_str = f"{row['Date']} {row['Time']}"
            for fmt in ("%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M",
                        "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(dt_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                dt = datetime.strptime(dt_str, "%Y.%m.%d %H:%M")
            bars.append({
                "time": dt,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(float(row.get("Volume", 0)))
            })
    return bars


def get_bars(data_dir: str, symbol: str, tf: str) -> list[dict]:
    """Load bars for a given symbol and timeframe from data_dir.
    Expected filename: {symbol}_{tf}.csv or {symbol}_{tf}.csv.
    """
    for fname in (f"{symbol}_{tf}.csv", f"{symbol}_{tf.upper()}.csv",
                  f"{symbol}_{tf.lower()}.csv", f"{tf}.csv"):
        path = os.path.join(data_dir, fname)
        if os.path.exists(path):
            return load_csv(path)
    return []


# ───────────────────────────── TIME HELPERS ─────────────────────────────

def get_ny_time(dt: datetime) -> datetime:
    """Stub: returns dt as-is. Replace with pytz for real NY time."""
    return dt


# ───────────────────────────── BAR HELPERS ─────────────────────────────

def get_bar(bars: list[dict], offset: int = -1) -> Optional[dict]:
    if not bars:
        return None
    return bars[offset]


# ───────────────────────────── FVG DETECTION ─────────────────────────────

def detect_fvg(bars: list[dict], min_gap_pips: float = 0.5) -> list[dict]:
    """Detect Fair Value Gaps (3-candle gap pattern)."""
    fvgs = []
    for i in range(1, len(bars) - 1):
        gap = bars[i + 1]["low"] - bars[i - 1]["high"]
        if gap > 0 and gap >= min_gap_pips * 0.0001:
            fvgs.append({
                "index": i, "direction": "bullish",
                "low": bars[i - 1]["high"], "high": bars[i + 1]["low"],
                "time": bars[i]["time"], "gap": gap
            })
        gap2 = bars[i - 1]["low"] - bars[i + 1]["high"]
        if gap2 > 0 and gap2 >= min_gap_pips * 0.0001:
            fvgs.append({
                "index": i, "direction": "bearish",
                "low": bars[i + 1]["high"], "high": bars[i - 1]["low"],
                "time": bars[i]["time"], "gap": gap2
            })
    return fvgs


def detect_ifvg(bars: list[dict], min_gap_pips: float = 0.3) -> list[dict]:
    """Detect Inverted FVGs - gaps that have been consumed by price."""
    fvgs = detect_fvg(bars, min_gap_pips)
    now = bars[-1]
    inverted = []
    for fvg in fvgs:
        if fvg["direction"] == "bullish" and now["close"] > fvg["high"]:
            inverted.append({**fvg, "inverted_at": now["time"], "type": "IFVG"})
        elif fvg["direction"] == "bearish" and now["close"] < fvg["low"]:
            inverted.append({**fvg, "inverted_at": now["time"], "type": "IFVG"})
    return inverted


def get_unmitigated_fvgs(fvgs: list[dict], bars: list[dict]) -> list[dict]:
    """Filter FVGs that have not been touched by price."""
    unmit = []
    for fvg in fvgs:
        touched = False
        for b in bars:
            if fvg["direction"] == "bullish" and b["low"] <= fvg["high"]:
                touched = True
                break
            elif fvg["direction"] == "bearish" and b["high"] >= fvg["low"]:
                touched = True
                break
        if not touched:
            unmit.append(fvg)
    return unmit


# ───────────────────────────── SWING DETECTION ─────────────────────────────

def detect_swing_highs(bars: list[dict], lookback: int = 2) -> list[dict]:
    """Detect swing highs using local peak comparison."""
    highs = []
    for i in range(lookback, len(bars) - lookback):
        if all(bars[i]["high"] > bars[i - j]["high"] for j in range(1, lookback + 1)) and \
           all(bars[i]["high"] > bars[i + j]["high"] for j in range(1, lookback + 1)):
            highs.append({
                "index": i, "price": bars[i]["high"],
                "time": bars[i]["time"]
            })
    return highs


def detect_swing_lows(bars: list[dict], lookback: int = 2) -> list[dict]:
    """Detect swing lows using local trough comparison."""
    lows = []
    for i in range(lookback, len(bars) - lookback):
        if all(bars[i]["low"] < bars[i - j]["low"] for j in range(1, lookback + 1)) and \
           all(bars[i]["low"] < bars[i + j]["low"] for j in range(1, lookback + 1)):
            lows.append({
                "index": i, "price": bars[i]["low"],
                "time": bars[i]["time"]
            })
    return lows


# ───────────────────────────── STRUCTURE SHIFTS ─────────────────────────────

def detect_mss(bars: list[dict], lookback: int = 2) -> list[dict]:
    """Detect Market Structure Shift (break of recent swing)."""
    shifts = []
    if len(bars) < lookback + 2:
        return shifts
    recent = bars[-(lookback + 2):]
    if recent[-1]["low"] > recent[-2]["low"] and recent[-3]["low"] > recent[-2]["low"]:
        shifts.append({"index": len(bars) - 1, "direction": "bullish", "time": bars[-1]["time"]})
    if recent[-1]["high"] < recent[-2]["high"] and recent[-3]["high"] < recent[-2]["high"]:
        shifts.append({"index": len(bars) - 1, "direction": "bearish", "time": bars[-1]["time"]})
    return shifts


def detect_cisd(bars: list[dict]) -> list[dict]:
    """Change in State of Delivery: aggressive close past recent range."""
    signals = []
    if len(bars) < 3:
        return signals
    recent = bars[-3:]
    if recent[-1]["close"] > recent[-2]["high"] and recent[-1]["close"] > recent[-3]["high"]:
        signals.append({"direction": "bullish", "time": recent[-1]["time"], "price": recent[-1]["close"]})
    if recent[-1]["close"] < recent[-2]["low"] and recent[-1]["close"] < recent[-3]["low"]:
        signals.append({"direction": "bearish", "time": recent[-1]["time"], "price": recent[-1]["close"]})
    return signals


# ───────────────────────────── ORDER FLOW ─────────────────────────────

def is_bullish_orderflow(bars: list[dict], lookback: int = 20) -> bool:
    """Simple check: consecutive higher closes."""
    if len(bars) < lookback:
        return False
    closes = [b["close"] for b in bars[-lookback:]]
    rising = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
    return rising > len(closes) * 0.6


def is_bearish_orderflow(bars: list[dict], lookback: int = 20) -> bool:
    if len(bars) < lookback:
        return False
    closes = [b["close"] for b in bars[-lookback:]]
    falling = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i - 1])
    return falling > len(closes) * 0.6


# ───────────────────────────── VOLUME PROFILE ─────────────────────────────

def compute_volume_profile(bars: list[dict], row_size: float = 1.0,
                           va_volume: float = 0.70) -> Optional[dict]:
    """Build a volume profile from OHLCV bars, returning VAH, VAL, POC, shape."""
    if not bars:
        return None

    all_prices = []
    for b in bars:
        all_prices.extend([b["high"], b["low"]])
    min_p, max_p = min(all_prices), max(all_prices)

    rows = {}
    current = min_p
    while current <= max_p:
        rows[round(current, 5)] = 0
        current += row_size
    if not rows:
        return None

    for b in bars:
        keys = sorted(rows.keys())
        low_idx = min(keys, key=lambda x: abs(x - b["low"]))
        high_idx = min(keys, key=lambda x: abs(x - b["high"]))
        start = keys.index(low_idx)
        end = keys.index(high_idx)
        vol_per_row = b.get("volume", 1) / max(end - start, 1)
        for i in range(start, min(end + 1, len(keys))):
            rows[keys[i]] += vol_per_row

    total_vol = sum(rows.values())
    if total_vol == 0:
        return None

    poc_price = max(rows, key=rows.get)
    sorted_asc = sorted(rows.keys())
    poc_idx = sorted_asc.index(poc_price)

    va_vol_target = total_vol * va_volume
    cum_vol = rows[poc_price]
    va_prices = {poc_price}
    left = poc_idx - 1
    right = poc_idx + 1

    while cum_vol < va_vol_target and (left >= 0 or right < len(sorted_asc)):
        lv = rows[sorted_asc[left]] if left >= 0 else 0
        rv = rows[sorted_asc[right]] if right < len(sorted_asc) else 0
        if lv >= rv and left >= 0:
            cum_vol += lv
            va_prices.add(sorted_asc[left])
            left -= 1
        elif right < len(sorted_asc):
            cum_vol += rv
            va_prices.add(sorted_asc[right])
            right += 1
        else:
            break

    val = min(va_prices)
    vah = max(va_prices)
    va_range = vah - val

    shape = "D"
    if va_range > 0:
        poc_pos = (poc_price - val) / va_range
        if poc_pos > 0.6:
            shape = "P"
        elif poc_pos < 0.4:
            shape = "b"

    return {
        "vah": vah, "val": val, "poc": poc_price,
        "shape": shape, "total_volume": total_vol,
        "row_size": row_size
    }


# ───────────────────────────── SMT DIVERGENCE ─────────────────────────────

def detect_smt_divergence(
    primary_bars: list[dict],
    secondary_bars: list[dict],
    direction: str,
    lookback: int = 5
) -> bool:
    """SMT divergence between two correlated assets."""
    if len(primary_bars) < lookback or len(secondary_bars) < lookback:
        return False
    p1, p2 = primary_bars[-lookback], primary_bars[-1]
    s1, s2 = secondary_bars[-lookback], secondary_bars[-1]

    if direction == "bearish":
        return p2["high"] > p1["high"] and s2["high"] < s1["high"]
    elif direction == "bullish":
        return p2["low"] < p1["low"] and s2["low"] > s1["low"]
    return False


# ───────────────────────────── LIQUIDITY ─────────────────────────────

def detect_equal_highs(bars: list[dict], tolerance_pct: float = 0.0005) -> list[dict]:
    """Find equal highs (potential liquidity pools)."""
    eq_highs = []
    for i in range(len(bars) - 1):
        for j in range(i + 1, min(i + 10, len(bars))):
            diff = abs(bars[i]["high"] - bars[j]["high"]) / bars[i]["high"]
            if diff < tolerance_pct:
                eq_highs.append({
                    "price": bars[i]["high"],
                    "times": [bars[i]["time"], bars[j]["time"]]
                })
    return eq_highs


def detect_equal_lows(bars: list[dict], tolerance_pct: float = 0.0005) -> list[dict]:
    """Find equal lows (potential liquidity pools)."""
    eq_lows = []
    for i in range(len(bars) - 1):
        for j in range(i + 1, min(i + 10, len(bars))):
            diff = abs(bars[i]["low"] - bars[j]["low"]) / bars[i]["low"]
            if diff < tolerance_pct:
                eq_lows.append({
                    "price": bars[i]["low"],
                    "times": [bars[i]["time"], bars[j]["time"]]
                })
    return eq_lows


# ───────────────────────────── FIBONACCI ─────────────────────────────

def fib_expansion(start: float, end: float, level: float = 2.0) -> float:
    """Fibonacci expansion: end + (end - start) * level"""
    return end + (end - start) * level


def fib_retracement(high: float, low: float, level: float = 0.5) -> float:
    """Fibonacci retracement: high - (high - low) * level"""
    return high - (high - low) * level


# ───────────────────────────── TRADE & EVENT LOGGING ─────────────────────────────

class EventLog:
    """Collects all events during a strategy run for JSON output."""

    def __init__(self):
        self.events: list[dict] = []
        self.trades: list[dict] = []

    def event(self, step: int, name: str, time, price, tf: str,
              details: str = ""):
        self.events.append({
            "step": step, "event": name,
            "datetime": str(time) if hasattr(time, "strftime") else str(time),
            "price": round(price, 5) if price else None,
            "timeframe": tf, "details": details
        })

    def trade(self, direction: str, entry: float, sl: float, tp: float,
              time, symbol: str, strategy: str, extra: Optional[dict] = None):
        t = {
            "direction": direction,
            "entry": round(entry, 5),
            "stop_loss": round(sl, 5),
            "take_profit": round(tp, 5),
            "datetime": str(time) if hasattr(time, "strftime") else str(time),
            "symbol": symbol,
            "strategy": strategy
        }
        if extra:
            t.update(extra)
        self.trades.append(t)

    def to_json(self, output_path: str):
        result = {
            "events": self.events,
            "trades": self.trades,
            "summary": {
                "total_events": len(self.events),
                "total_trades": len(self.trades)
            }
        }
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
        return result


# ───────────────────────────── BAR FILTERS ─────────────────────────────

def filter_bars_by_time(bars: list[dict], start_hour: int, end_hour: int,
                        tz_func=get_ny_time) -> list[dict]:
    """Filter bars to a specific time window."""
    return [b for b in bars if start_hour <= tz_func(b["time"]).hour < end_hour]


def filter_bars_by_date(bars: list[dict], date: datetime) -> list[dict]:
    """Filter bars to a specific date."""
    return [b for b in bars if b["time"].date() == date.date()]


def group_bars_by_date(bars: list[dict]) -> dict:
    """Group bars by date."""
    groups = defaultdict(list)
    for b in bars:
        groups[b["time"].date()].append(b)
    return dict(groups)


# ───────────────────────────── BREAKER BLOCK ─────────────────────────────

def detect_breaker_block(bars: list[dict]) -> Optional[dict]:
    """Detect a breaker block: a strong FVG break that reverses."""
    if len(bars) < 5:
        return None
    fvgs = detect_fvg(bars[-5:], min_gap_pips=0.3)
    for fvg in fvgs:
        inv = detect_ifvg(bars[-5:], min_gap_pips=0.3)
        for i in inv:
            if i["index"] == fvg["index"]:
                return {
                    "type": "breaker_block",
                    "direction": "bullish" if fvg["direction"] == "bearish" else "bearish",
                    "time": bars[-1]["time"],
                    "price": bars[-1]["close"]
                }
    return None


# ───────────────────────────── OTE ─────────────────────────────

def optimal_trade_entry(high: float, low: float) -> dict:
    """70.5% Fibonacci retracement level for OTE."""
    fib_705 = high - (high - low) * 0.705
    fib_50 = high - (high - low) * 0.50
    return {"ote_level": fib_705, "mid_level": fib_50, "range": high - low}


# ───────────────────────────── CSV DATA LOADER (multi-timeframe) ──────────

def load_all_timeframes(data_dir: str, symbol: str,
                        timeframes: list[str]) -> dict[str, list[dict]]:
    """Load multiple timeframe CSVs into a dict."""
    result = {}
    for tf in timeframes:
        bars = get_bars(data_dir, symbol, tf)
        if bars:
            result[tf] = bars
    return result


def parse_args_standalone() -> dict:
    """Simple arg parser for standalone scripts."""
    import sys
    args = {
        "symbol": "NQ",
        "data_dir": ".",
        "output": "output.json",
        "files": {}
    }
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--symbol" and i + 1 < len(argv):
            args["symbol"] = argv[i + 1]
        elif a == "--data" and i + 1 < len(argv):
            args["data_dir"] = argv[i + 1]
        elif a == "--output" and i + 1 < len(argv):
            args["output"] = argv[i + 1]
        elif a.startswith("--") and "=" in a:
            k, v = a[2:].split("=", 1)
            args[k] = v
    return args
