"""
Orderflow absorption proxies using tick volume and wick structure.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str
    cluster_price: float
    absorption_high: float
    absorption_low: float
    volume_ratio: float


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """Return upper-wick and lower-wick volume share estimates."""
    total = max(bar.tick_volume, 1)
    body = max(bar.body_size, 1e-9)
    upper = max(bar.upper_wick, 0.0)
    lower = max(bar.lower_wick, 0.0)
    wick_total = upper + lower
    if wick_total <= 0:
        return 0.0, 0.0
    upper_share = (upper / wick_total) * (wick_total / (body + wick_total))
    lower_share = (lower / wick_total) * (wick_total / (body + wick_total))
    return upper_share * total, lower_share * total


def detect_buyer_absorption(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    """Heavy buying in upper wick without bullish follow-through."""
    if bar.total_range <= 0:
        return False
    upper_wick_share = bar.upper_wick / bar.total_range
    return (
        upper_wick_share >= min_wick_ratio
        and bar.tick_volume > 0
        and not bar.is_bullish
    )


def detect_seller_absorption(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    """Heavy selling in lower wick without bearish follow-through."""
    if bar.total_range <= 0:
        return False
    lower_wick_share = bar.lower_wick / bar.total_range
    return (
        lower_wick_share >= min_wick_ratio
        and bar.tick_volume > 0
        and not bar.is_bearish
    )


def find_volume_cluster_level(bars: list[Bar], lookback: int = 8) -> float | None:
    """Return close of highest tick-volume bar in recent window."""
    window = bars[-lookback:]
    if not window:
        return None
    cluster_bar = max(window, key=lambda bar: bar.tick_volume)
    return cluster_bar.close


def price_near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct
