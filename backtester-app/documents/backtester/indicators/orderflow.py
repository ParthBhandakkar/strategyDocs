"""
Orderflow approximations using tick_volume (no L2 footprint data).
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    """Detected wick absorption on a bar."""
    bar_index: int
    direction: str  # "buyer" (upper wick) or "seller" (lower wick)
    cluster_price: float
    wick_extreme: float


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """Return (upper_wick_vol_ratio, lower_wick_vol_ratio) using tick_volume."""
    vol = bar.tick_volume or 1
    total_range = bar.total_range
    if total_range <= 0:
        return 0.0, 0.0
    upper_share = bar.upper_wick / total_range
    lower_share = bar.lower_wick / total_range
    return upper_share * vol, lower_share * vol


def is_buyer_absorption(bar: Bar, min_wick_ratio: float = 0.45, min_volume: int = 50) -> bool:
    """
    Buyer absorption: heavy activity in upper wick without bullish follow-through.
    Wick vs body rule from Video #1.
    """
    if bar.total_range <= 0:
        return False
    upper_ratio = bar.upper_wick / bar.total_range
    body_ratio = bar.body_size / bar.total_range
    vol = bar.tick_volume or 0
    return (
        upper_ratio >= min_wick_ratio
        and body_ratio < 0.35
        and vol >= min_volume
        and bar.close <= bar.body_high
    )


def is_seller_absorption(bar: Bar, min_wick_ratio: float = 0.45, min_volume: int = 50) -> bool:
    """Seller absorption at lower wick without bearish follow-through."""
    if bar.total_range <= 0:
        return False
    lower_ratio = bar.lower_wick / bar.total_range
    body_ratio = bar.body_size / bar.total_range
    vol = bar.tick_volume or 0
    return (
        lower_ratio >= min_wick_ratio
        and body_ratio < 0.35
        and vol >= min_volume
        and bar.close >= bar.body_low
    )


def find_recent_support_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Nearest swing-low cluster price from recent bars (order inversion reference)."""
    if len(bars) < 3:
        return None
    recent = bars[-lookback:]
    lows = [b.low for b in recent if b.is_bullish or b.close > b.open]
    if not lows:
        return None
    return min(lows)


def find_recent_resistance_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Nearest swing-high cluster from recent bars."""
    if len(bars) < 3:
        return None
    recent = bars[-lookback:]
    highs = [b.high for b in recent if b.is_bearish or b.close < b.open]
    if not highs:
        return None
    return max(highs)
