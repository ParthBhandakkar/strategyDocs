"""
Orderflow absorption approximations using tick volume in wicks vs bodies.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str
    bar_index: int
    cluster_price: float
    absorption_high: float
    absorption_low: float
    volume_score: float


def wick_volume_ratio(bar: Bar, side: str) -> float:
    """
    Approximate orderflow concentration in wicks using tick volume.
    side: 'upper' or 'lower'
    """
    total = bar.total_range
    if total <= 0:
        return 0.0
    if side == "upper":
        wick = bar.upper_wick
    else:
        wick = bar.lower_wick
    if wick <= 0:
        return 0.0
    body = max(bar.body_size, total * 0.05)
    wick_share = wick / total
    return (bar.tick_volume or 1) * wick_share / body


def detect_buyer_absorption(bar: Bar, min_ratio: float = 1.5) -> bool:
    """Heavy buying in upper wick without bullish close follow-through."""
    if not bar.is_bullish and bar.upper_wick <= bar.lower_wick:
        return False
    return wick_volume_ratio(bar, "upper") >= min_ratio and bar.upper_wick > bar.body_size * 0.5


def detect_seller_absorption(bar: Bar, min_ratio: float = 1.5) -> bool:
    """Heavy selling in lower wick without bearish close follow-through."""
    if not bar.is_bearish and bar.lower_wick <= bar.upper_wick:
        return False
    return wick_volume_ratio(bar, "lower") >= min_ratio and bar.lower_wick > bar.body_size * 0.5


def find_local_support_cluster(bars: list[Bar], lookback: int = 8) -> tuple[float, float]:
    """
    Proxy for close-proximity order cluster: recent swing low zone.
    Returns (cluster_low, cluster_high).
    """
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if not window:
        return 0.0, 0.0
    lows = [b.low for b in window]
    cluster_low = min(lows)
    cluster_high = min(b.close for b in window[-3:]) if len(window) >= 3 else cluster_low
    return cluster_low, max(cluster_high, cluster_low)


def find_local_resistance_cluster(bars: list[Bar], lookback: int = 8) -> tuple[float, float]:
    """Proxy for close-proximity sell cluster: recent swing high zone."""
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if not window:
        return 0.0, 0.0
    highs = [b.high for b in window]
    cluster_high = max(highs)
    cluster_low = max(b.close for b in window[-3:]) if len(window) >= 3 else cluster_high
    return min(cluster_low, cluster_high), cluster_high
