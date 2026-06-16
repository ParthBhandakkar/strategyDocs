"""Volume-profile orderflow absorption helpers."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionEvent:
    direction: str  # "buyer" or "seller"
    bar_time: object
    cluster_low: float
    cluster_high: float
    wick_extreme: float


def _wick_volume_share(bar: Bar) -> tuple[float, float]:
    """Approximate upper/lower wick volume share using tick volume."""
    vol = max(bar.tick_volume, 1)
    total_range = max(bar.total_range, 1e-9)
    upper_share = bar.upper_wick / total_range
    lower_share = bar.lower_wick / total_range
    return vol * upper_share, vol * lower_share


def detect_buyer_absorption(bar: Bar, min_wick_ratio: float = 0.45, min_volume: int = 50) -> bool:
    """Heavy volume in upper wick with stalled bullish follow-through."""
    if bar.total_range <= 0:
        return False
    upper_vol, _ = _wick_volume_share(bar)
    wick_ratio = bar.upper_wick / bar.total_range
    body_ratio = bar.body_size / bar.total_range
    return (
        wick_ratio >= min_wick_ratio
        and upper_vol >= min_volume
        and body_ratio <= 0.55
        and bar.close <= bar.open + bar.body_size * 0.6
    )


def detect_seller_absorption(bar: Bar, min_wick_ratio: float = 0.45, min_volume: int = 50) -> bool:
    """Heavy volume in lower wick without continued downside."""
    if bar.total_range <= 0:
        return False
    _, lower_vol = _wick_volume_share(bar)
    wick_ratio = bar.lower_wick / bar.total_range
    body_ratio = bar.body_size / bar.total_range
    return (
        wick_ratio >= min_wick_ratio
        and lower_vol >= min_volume
        and body_ratio <= 0.55
        and bar.close >= bar.open - bar.body_size * 0.6
    )


def find_recent_support_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Recent swing low used as close-proximity support cluster."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    lows = [b.low for b in window[:-1]]
    if not lows:
        return None
    return min(lows)


def find_recent_resistance_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    highs = [b.high for b in window[:-1]]
    if not highs:
        return None
    return max(highs)
