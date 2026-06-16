"""
Orderflow absorption approximations using tick volume in wicks.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    kind: str
    cluster_price: float
    wick_high: float
    wick_low: float
    volume_ratio: float


def wick_volume_ratio(bar: Bar, side: str) -> float:
    """Estimate volume concentration in upper or lower wick."""
    total = bar.tick_volume or 1
    body = max(bar.body_size, 1e-9)
    if side == "upper":
        wick = max(bar.upper_wick, 1e-9)
    else:
        wick = max(bar.lower_wick, 1e-9)
    range_size = max(bar.total_range, 1e-9)
    wick_share = wick / range_size
    return (total * wick_share) / body


def detect_buyer_absorption(
    bar: Bar,
    min_wick_ratio: float = 1.5,
    min_upper_wick_pips: float = 0.0,
) -> bool:
    """Heavy buying in upper wick without bullish follow-through."""
    if bar.upper_wick <= 0:
        return False
    if bar.is_bullish and bar.close >= bar.high - bar.total_range * 0.15:
        return False
    return wick_volume_ratio(bar, "upper") >= min_wick_ratio and bar.upper_wick >= min_upper_wick_pips


def detect_seller_absorption(
    bar: Bar,
    min_wick_ratio: float = 1.5,
    min_lower_wick_pips: float = 0.0,
) -> bool:
    """Heavy selling in lower wick without bearish follow-through."""
    if bar.lower_wick <= 0:
        return False
    if bar.is_bearish and bar.close <= bar.low + bar.total_range * 0.15:
        return False
    return wick_volume_ratio(bar, "lower") >= min_wick_ratio and bar.lower_wick >= min_lower_wick_pips


def nearest_support_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Proxy for close-proximity aggressive buy cluster using recent swing lows."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    return min(bar.low for bar in window)


def nearest_resistance_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Proxy for close-proximity aggressive sell cluster using recent swing highs."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    return max(bar.high for bar in window)
