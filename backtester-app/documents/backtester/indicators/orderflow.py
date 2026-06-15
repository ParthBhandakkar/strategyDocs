"""
Orderflow absorption approximations using tick volume in wicks vs bodies.
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
    wick_volume_ratio: float


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """Return (upper_wick_ratio, lower_wick_ratio) of tick volume in wicks."""
    total = bar.tick_volume or 1
    body = max(bar.body_size, 1e-9)
    total_range = max(bar.total_range, 1e-9)

    upper_share = bar.upper_wick / total_range
    lower_share = bar.lower_wick / total_range
    body_share = max(0.0, 1.0 - upper_share - lower_share)

    upper_vol = total * upper_share
    lower_vol = total * lower_share
    body_vol = total * body_share

    upper_ratio = upper_vol / max(body_vol, 1.0)
    lower_ratio = lower_vol / max(body_vol, 1.0)
    return upper_ratio, lower_ratio


def detect_buyer_absorption(bar: Bar, min_wick_ratio: float = 1.5) -> bool:
    """Heavy buying in upper wick without bullish follow-through."""
    upper_ratio, _ = wick_volume_ratio(bar)
    return upper_ratio >= min_wick_ratio and bar.upper_wick >= bar.body_size * 0.3


def detect_seller_absorption(bar: Bar, min_wick_ratio: float = 1.5) -> bool:
    """Heavy selling in lower wick without bearish follow-through."""
    _, lower_ratio = wick_volume_ratio(bar)
    return lower_ratio >= min_wick_ratio and bar.lower_wick >= bar.body_size * 0.3


def find_support_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Nearest swing-low support from recent bars."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    lows = [b.low for b in window[:-1]]
    if not lows:
        return None
    return min(lows)


def find_resistance_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Nearest swing-high resistance from recent bars."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    highs = [b.high for b in window[:-1]]
    if not highs:
        return None
    return max(highs)
