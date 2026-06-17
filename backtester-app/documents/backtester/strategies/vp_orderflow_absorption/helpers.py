"""
VP Orderflow Absorption — strategy-specific helpers.
Approximates orderflow absorption using tick volume in wicks.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


@dataclass
class AbsorptionEvent:
    direction: str  # "buyer" or "seller"
    bar_index: int
    cluster_low: float
    cluster_high: float
    wick_extreme: float


def upper_wick_volume_ratio(bar: Bar) -> float:
    total = bar.tick_volume or 1
    if bar.total_range <= 0:
        return 0.0
    upper_share = bar.upper_wick / bar.total_range
    return upper_share * total


def lower_wick_volume_ratio(bar: Bar) -> float:
    total = bar.tick_volume or 1
    if bar.total_range <= 0:
        return 0.0
    lower_share = bar.lower_wick / bar.total_range
    return lower_share * total


def is_buyer_absorption(bar: Bar, volume_threshold: float) -> bool:
    if bar.total_range <= 0:
        return False
    wick_heavy = bar.upper_wick > bar.body_size
    stalled = bar.close <= bar.open + bar.upper_wick * 0.35
    return wick_heavy and stalled and upper_wick_volume_ratio(bar) >= volume_threshold


def is_seller_absorption(bar: Bar, volume_threshold: float) -> bool:
    if bar.total_range <= 0:
        return False
    wick_heavy = bar.lower_wick > bar.body_size
    stalled = bar.close >= bar.open - bar.lower_wick * 0.35
    return wick_heavy and stalled and lower_wick_volume_ratio(bar) >= volume_threshold


def volume_threshold_from_history(bars: list[Bar], percentile: float = 0.65) -> float:
    if not bars:
        return 1.0
    scores = [max(upper_wick_volume_ratio(b), lower_wick_volume_ratio(b)) for b in bars[-60:]]
    scores.sort()
    idx = int(len(scores) * percentile)
    idx = min(max(idx, 0), len(scores) - 1)
    return max(scores[idx], 1.0)


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def compute_developing_vp(session_bars: list[Bar]) -> VolumeProfile | None:
    if len(session_bars) < 10:
        return None
    return compute_frvp(session_bars)


def find_recent_support_cluster(bars: list[Bar], lookback: int = 8) -> tuple[float, float] | None:
    window = bars[-lookback:]
    if len(window) < 3:
        return None
    lows = [b.low for b in window[:-1]]
    cluster_low = min(lows)
    cluster_high = max(b.close for b in window[:-1] if b.low <= cluster_low * 1.0003)
    if cluster_high <= cluster_low:
        cluster_high = cluster_low + (window[-1].total_range or cluster_low * 0.0001)
    return cluster_low, cluster_high


def find_recent_resistance_cluster(bars: list[Bar], lookback: int = 8) -> tuple[float, float] | None:
    window = bars[-lookback:]
    if len(window) < 3:
        return None
    highs = [b.high for b in window[:-1]]
    cluster_high = max(highs)
    cluster_low = min(b.close for b in window[:-1] if b.high >= cluster_high * 0.9997)
    if cluster_low >= cluster_high:
        cluster_low = cluster_high - (window[-1].total_range or cluster_high * 0.0001)
    return cluster_low, cluster_high
