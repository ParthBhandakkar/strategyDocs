"""
Orderflow absorption proxies using tick volume (no L2 data).
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    side: str
    level: float
    bar_time: object


def wick_volume_ratio(bar: Bar, side: str) -> float:
    """Share of bar volume attributed to upper or lower wick."""
    total = bar.tick_volume or 1
    bar_range = bar.total_range
    if bar_range <= 0:
        return 0.0
    if side == "upper":
        wick = bar.upper_wick
    else:
        wick = bar.lower_wick
    return (wick / bar_range) * total


def is_buyer_absorption(bar: Bar, min_wick_ratio: float = 0.45, min_volume: int = 50) -> bool:
    """
    Heavy activity in upper wick without bullish follow-through.
    Proxy for aggressive buyers absorbed at highs.
    """
    if bar.total_range <= 0:
        return False
    upper_share = bar.upper_wick / bar.total_range
    volume = bar.tick_volume or 0
    stalled = bar.close <= bar.open + bar.body_size * 0.35
    return upper_share >= min_wick_ratio and volume >= min_volume and stalled


def is_seller_absorption(bar: Bar, min_wick_ratio: float = 0.45, min_volume: int = 50) -> bool:
    """Heavy activity in lower wick without bearish follow-through."""
    if bar.total_range <= 0:
        return False
    lower_share = bar.lower_wick / bar.total_range
    volume = bar.tick_volume or 0
    stalled = bar.close >= bar.open - bar.body_size * 0.35
    return lower_share >= min_wick_ratio and volume >= min_volume and stalled


def recent_support_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Lowest low cluster in recent bars — proxy for order support."""
    window = bars[-lookback:]
    if len(window) < 3:
        return None
    return min(b.low for b in window)


def recent_resistance_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    window = bars[-lookback:]
    if len(window) < 3:
        return None
    return max(b.high for b in window)
