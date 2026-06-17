"""VP + orderflow absorption helpers (strategy-local volume proxy)."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionBar:
    bar: Bar
    kind: str  # buyer_absorption | seller_absorption
    cluster_low: float
    cluster_high: float


def is_buyer_absorption(bar: Bar, vol_threshold: int = 50) -> bool:
    """High volume in upper wick with weak bullish follow-through body."""
    if bar.total_range <= 0:
        return False
    upper_ratio = bar.upper_wick / bar.total_range
    body_ratio = bar.body_size / bar.total_range
    vol = bar.tick_volume or 0
    return vol >= vol_threshold and upper_ratio >= 0.35 and body_ratio <= 0.45


def is_seller_absorption(bar: Bar, vol_threshold: int = 50) -> bool:
    if bar.total_range <= 0:
        return False
    lower_ratio = bar.lower_wick / bar.total_range
    body_ratio = bar.body_size / bar.total_range
    vol = bar.tick_volume or 0
    return vol >= vol_threshold and lower_ratio >= 0.35 and body_ratio <= 0.45


def recent_swing_low(bars: list[Bar], lookback: int = 8) -> float | None:
    window = bars[-lookback:]
    if len(window) < 3:
        return None
    return min(b.low for b in window[:-1])


def recent_swing_high(bars: list[Bar], lookback: int = 8) -> float | None:
    window = bars[-lookback:]
    if len(window) < 3:
        return None
    return max(b.high for b in window[:-1])
