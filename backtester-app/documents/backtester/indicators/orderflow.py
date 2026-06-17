"""
Orderflow absorption proxies using OHLCV + tick_volume (no L2 data).
"""
from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str
    absorption_price: float
    cluster_level: float
    bar_index: int


def wick_volume_share(bar: Bar) -> tuple[float, float]:
    """Return upper-wick and lower-wick volume share estimates."""
    total = max(bar.tick_volume, 1)
    if bar.total_range <= 0:
        return 0.0, 0.0
    upper_share = bar.upper_wick / bar.total_range
    lower_share = bar.lower_wick / bar.total_range
    return upper_share * total, lower_share * total


def detect_buyer_absorption_at_high(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    """
    Buyer absorption: heavy activity in upper wick without bullish follow-through.
    Proxy: upper wick dominates range and close fails to hold near high.
    """
    if bar.total_range <= 0:
        return False
    upper_ratio = bar.upper_wick / bar.total_range
    close_position = (bar.close - bar.low) / bar.total_range
    return upper_ratio >= min_wick_ratio and close_position < 0.65


def detect_seller_absorption_at_low(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    """Seller absorption at lows: heavy lower-wick activity without breakdown."""
    if bar.total_range <= 0:
        return False
    lower_ratio = bar.lower_wick / bar.total_range
    close_position = (bar.close - bar.low) / bar.total_range
    return lower_ratio >= min_wick_ratio and close_position > 0.35


def find_recent_support_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Recent swing-low cluster for order inversion trigger."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    lows = sorted(b.low for b in window)
    return lows[1] if len(lows) > 1 else lows[0]


def find_recent_resistance_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Recent swing-high cluster for bullish inversion trigger."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    highs = sorted((b.high for b in window), reverse=True)
    return highs[1] if len(highs) > 1 else highs[0]
