"""
Orderflow approximations from OHLCV tick volume (no L2 data).
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str
    absorption_high: float
    absorption_low: float
    cluster_level: float
    volume_ratio: float


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """Return upper-wick and lower-wick volume concentration proxies."""
    total_range = max(bar.total_range, 1e-9)
    volume = max(bar.tick_volume, 1)
    upper_share = bar.upper_wick / total_range
    lower_share = bar.lower_wick / total_range
    return upper_share * volume, lower_share * volume


def detect_buyer_absorption(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    """Heavy volume trapped in upper wick without bullish follow-through."""
    if bar.total_range <= 0:
        return False
    upper_share = bar.upper_wick / bar.total_range
    return upper_share >= min_wick_ratio and bar.close <= bar.body_high


def detect_seller_absorption(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    """Heavy volume trapped in lower wick without bearish follow-through."""
    if bar.total_range <= 0:
        return False
    lower_share = bar.lower_wick / bar.total_range
    return lower_share >= min_wick_ratio and bar.close >= bar.body_low


def find_recent_support_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Nearest local swing low used as a close-proximity support cluster."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    for idx in range(len(window) - 2, 0, -1):
        prev_bar = window[idx - 1]
        bar = window[idx]
        next_bar = window[idx + 1]
        if bar.low <= prev_bar.low and bar.low <= next_bar.low:
            return bar.low
    return window[-2].low if len(window) >= 2 else None


def find_recent_resistance_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Nearest local swing high used as a close-proximity resistance cluster."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    for idx in range(len(window) - 2, 0, -1):
        prev_bar = window[idx - 1]
        bar = window[idx]
        next_bar = window[idx + 1]
        if bar.high >= prev_bar.high and bar.high >= next_bar.high:
            return bar.high
    return window[-2].high if len(window) >= 2 else None
