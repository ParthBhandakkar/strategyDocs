"""
Orderflow absorption proxies using tick_volume in candle wicks.
Approximates L2 absorption when aggressive volume prints in wicks without follow-through.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str  # "buyer_absorption" or "seller_absorption"
    bar: Bar
    wick_volume_ratio: float
    cluster_level: float


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """
    Estimate upper/lower wick volume share.
    Returns (upper_wick_ratio, lower_wick_ratio) summing to ~1 when body exists.
    """
    total = bar.tick_volume or 1
    body = max(bar.body_size, bar.total_range * 0.01)
    upper = bar.upper_wick
    lower = bar.lower_wick
    wick_total = upper + lower
    if wick_total <= 0:
        return 0.0, 0.0
    upper_share = (upper / wick_total) * min(1.0, wick_total / body)
    lower_share = (lower / wick_total) * min(1.0, wick_total / body)
    norm = upper_share + lower_share
    if norm <= 0:
        return 0.0, 0.0
    return upper_share / norm, lower_share / norm


def detect_buyer_absorption(bar: Bar, min_wick_ratio: float = 0.55) -> bool:
    """Heavy buying in upper wick without bullish close follow-through."""
    if not bar.is_bullish and bar.upper_wick <= bar.body_size:
        return False
    upper_ratio, _ = wick_volume_ratio(bar)
    return upper_ratio >= min_wick_ratio and bar.upper_wick > bar.body_size * 0.5


def detect_seller_absorption(bar: Bar, min_wick_ratio: float = 0.55) -> bool:
    """Heavy selling in lower wick without bearish close follow-through."""
    if not bar.is_bearish and bar.lower_wick <= bar.body_size:
        return False
    _, lower_ratio = wick_volume_ratio(bar)
    return lower_ratio >= min_wick_ratio and bar.lower_wick > bar.body_size * 0.5


def find_support_cluster(bars: list[Bar], lookback: int = 5) -> float | None:
    """Recent swing low cluster for inversion short trigger."""
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    return min(b.low for b in window)


def find_resistance_cluster(bars: list[Bar], lookback: int = 5) -> float | None:
    """Recent swing high cluster for inversion long trigger."""
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    return max(b.high for b in window)
