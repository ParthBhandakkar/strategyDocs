"""
Orderflow approximations using tick_volume on OHLCV bars.
Used when Level-2 data is unavailable (CSV backtests).
"""
from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    """Detected wick absorption on a bar."""
    bar_index: int
    direction: str  # "buyer_absorption" (bearish fade) or "seller_absorption" (bullish fade)
    cluster_price: float
    wick_extreme: float
    volume_ratio: float


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """
    Estimate volume concentration in upper vs lower wick.
    Returns (upper_wick_vol_ratio, lower_wick_vol_ratio) summing to ~1.0.
    """
    vol = bar.tick_volume or 1
    total_range = bar.total_range
    if total_range <= 0:
        return 0.0, 0.0

    upper = bar.upper_wick / total_range
    lower = bar.lower_wick / total_range
    body = bar.body_size / total_range
    # Body volume split proportional to wick sizes for remainder
    body_share = max(0.0, 1.0 - upper - lower)
    return upper * vol, (lower * vol) + (body_share * vol * 0.5)


def detect_buyer_absorption(bar: Bar, min_wick_ratio: float = 0.35, min_volume: int = 50) -> bool:
    """
    Heavy buy aggression in upper wick without bullish follow-through (close not at high).
    Proxy for institutional sell-side absorption at highs.
    """
    if bar.total_range <= 0 or (bar.tick_volume or 0) < min_volume:
        return False
    upper_ratio = bar.upper_wick / bar.total_range
    close_not_at_high = bar.close < bar.high - bar.total_range * 0.15
    return upper_ratio >= min_wick_ratio and close_not_at_high


def detect_seller_absorption(bar: Bar, min_wick_ratio: float = 0.35, min_volume: int = 50) -> bool:
    """
    Heavy sell aggression in lower wick without bearish follow-through (close not at low).
    Proxy for institutional buy-side absorption at lows.
    """
    if bar.total_range <= 0 or (bar.tick_volume or 0) < min_volume:
        return False
    lower_ratio = bar.lower_wick / bar.total_range
    close_not_at_low = bar.close > bar.low + bar.total_range * 0.15
    return lower_ratio >= min_wick_ratio and close_not_at_low


def find_support_cluster(bars: list[Bar], lookback: int = 10) -> float | None:
    """Recent swing low cluster — close proximity support for inversion check."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:] if len(bars) >= lookback else bars
    lows = [b.low for b in window[:-1]]
    if not lows:
        return None
    return min(lows)


def find_resistance_cluster(bars: list[Bar], lookback: int = 10) -> float | None:
    """Recent swing high cluster for long inversion check."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:] if len(bars) >= lookback else bars
    highs = [b.high for b in window[:-1]]
    if not highs:
        return None
    return max(highs)
