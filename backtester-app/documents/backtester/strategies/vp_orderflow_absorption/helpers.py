"""VP + orderflow absorption strategy helpers."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.volume_profile import wick_volume_ratio


ABSORPTION_WICK_RATIO = 0.45
ABSORPTION_MIN_VOLUME = 50
CLUSTER_LOOKBACK = 12
CLUSTER_TOUCH_TOLERANCE = 0.00015


@dataclass
class AbsorptionEvent:
    side: str
    bar: Bar
    cluster_level: float


def is_buyer_absorption(bar: Bar, min_volume: int = ABSORPTION_MIN_VOLUME) -> bool:
    if not bar.is_bullish:
        return False
    if bar.upper_wick <= 0:
        return False
    upper_vol, _ = wick_volume_ratio(bar)
    body_vol = (bar.tick_volume or 0) - upper_vol
    return (
        (bar.tick_volume or 0) >= min_volume
        and bar.upper_wick / max(bar.total_range, 1e-9) >= ABSORPTION_WICK_RATIO
        and upper_vol > body_vol
    )


def is_seller_absorption(bar: Bar, min_volume: int = ABSORPTION_MIN_VOLUME) -> bool:
    if not bar.is_bearish:
        return False
    if bar.lower_wick <= 0:
        return False
    _, lower_vol = wick_volume_ratio(bar)
    body_vol = (bar.tick_volume or 0) - lower_vol
    return (
        (bar.tick_volume or 0) >= min_volume
        and bar.lower_wick / max(bar.total_range, 1e-9) >= ABSORPTION_WICK_RATIO
        and lower_vol > body_vol
    )


def nearest_support_cluster(bars: list[Bar], lookback: int = CLUSTER_LOOKBACK) -> float | None:
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    lows = sorted({round(b.low, 5) for b in window})
    if not lows:
        return None
    return lows[max(0, len(lows) // 3)]


def nearest_resistance_cluster(bars: list[Bar], lookback: int = CLUSTER_LOOKBACK) -> float | None:
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    highs = sorted({round(b.high, 5) for b in window})
    if not highs:
        return None
    return highs[min(len(highs) - 1, (2 * len(highs)) // 3)]


def price_near_level(price: float, level: float, tolerance: float = CLUSTER_TOUCH_TOLERANCE) -> bool:
    return abs(price - level) <= max(abs(level) * tolerance, tolerance)
