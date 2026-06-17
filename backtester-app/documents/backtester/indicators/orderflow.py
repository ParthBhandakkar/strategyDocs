"""
Orderflow absorption proxies using tick_volume (no L2 data in CSV).
"""
from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str  # "buyer" or "seller"
    bar_index: int
    cluster_high: float
    cluster_low: float
    reference_price: float


def _avg_volume(bars: list[Bar], lookback: int = 20) -> float:
    if not bars:
        return 1.0
    sample = bars[-lookback:]
    return sum(b.tick_volume or 1 for b in sample) / len(sample)


def detect_wick_absorption(bar: Bar, avg_vol: float, min_vol_ratio: float = 1.5) -> str | None:
    """
    Wick absorption: heavy volume in wick without body follow-through.
    Returns 'buyer' (upper wick) or 'seller' (lower wick).
    """
    vol = bar.tick_volume or 1
    if vol < avg_vol * min_vol_ratio:
        return None
    body = max(bar.body_size, bar.midpoint * 1e-8)
    upper_ratio = bar.upper_wick / max(bar.total_range, body)
    lower_ratio = bar.lower_wick / max(bar.total_range, body)
    if upper_ratio >= 0.45 and bar.close <= bar.body_high:
        return "buyer"
    if lower_ratio >= 0.45 and bar.close >= bar.body_low:
        return "seller"
    return None


def find_order_cluster(
    bars: list[Bar],
    lookback: int = 5,
) -> tuple[float, float] | None:
    """Recent swing cluster high/low from last N bars."""
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    return min(b.low for b in window), max(b.high for b in window)


def vwap_from_bars(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    num = 0.0
    den = 0.0
    for bar in bars:
        vol = bar.tick_volume or 1
        typical = (bar.high + bar.low + bar.close) / 3.0
        num += typical * vol
        den += vol
    return num / den if den > 0 else bars[-1].close
