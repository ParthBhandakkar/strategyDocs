"""Strategy-specific helpers for VP orderflow absorption."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.orderflow_proxy import wick_volume_ratio


@dataclass
class AbsorptionEvent:
    direction: str  # "buyer_absorption" | "seller_absorption"
    bar: Bar
    level: float
    cluster_level: float


def is_buyer_absorption(bar: Bar, min_wick_ratio: float = 0.55) -> bool:
    """Heavy volume in upper wick without bullish follow-through."""
    upper, body, _ = wick_volume_ratio(bar)
    total = upper + body + 1e-9
    return upper / total >= min_wick_ratio and bar.upper_wick > bar.body_size


def is_seller_absorption(bar: Bar, min_wick_ratio: float = 0.55) -> bool:
    lower, body, _ = wick_volume_ratio(bar)
    total = lower + body + 1e-9
    return lower / total >= min_wick_ratio and bar.lower_wick > bar.body_size


def recent_swing_low(bars: list[Bar], lookback: int = 12) -> float | None:
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    return min(b.low for b in window[:-1])


def recent_swing_high(bars: list[Bar], lookback: int = 12) -> float | None:
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    return max(b.high for b in window[:-1])


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct
