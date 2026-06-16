"""
Shared orderflow absorption helpers using OHLCV + tick_volume proxies.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str
    absorption_price: float
    cluster_level: float
    volume_ratio: float


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """Return upper and lower wick volume ratios using tick_volume."""
    volume = max(bar.tick_volume, 1)
    total_range = max(bar.total_range, 1e-9)
    upper_share = bar.upper_wick / total_range
    lower_share = bar.lower_wick / total_range
    return upper_share * volume, lower_share * volume


def detect_buyer_absorption_at_highs(bar: Bar, min_wick_ratio: float = 0.35) -> bool:
    if bar.total_range <= 0:
        return False
    upper_wick_ratio = bar.upper_wick / bar.total_range
    return upper_wick_ratio >= min_wick_ratio and bar.close <= bar.body_high


def detect_seller_absorption_at_lows(bar: Bar, min_wick_ratio: float = 0.35) -> bool:
    if bar.total_range <= 0:
        return False
    lower_wick_ratio = bar.lower_wick / bar.total_range
    return lower_wick_ratio >= min_wick_ratio and bar.close >= bar.body_low


def find_local_support_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < lookback:
        return None
    window = bars[-lookback:-1]
    if not window:
        return None
    cluster = min(window, key=lambda item: item.low)
    if cluster.tick_volume <= 0:
        return cluster.low
    return cluster.low


def find_local_resistance_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < lookback:
        return None
    window = bars[-lookback:-1]
    if not window:
        return None
    cluster = max(window, key=lambda item: item.high)
    return cluster.high
