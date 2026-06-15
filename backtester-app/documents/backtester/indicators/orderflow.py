"""
Orderflow absorption proxies using tick_volume (no L2 data).
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str  # "buyer" or "seller"
    bar_index: int
    cluster_high: float
    cluster_low: float
    absorption_high: float
    absorption_low: float


def average_volume(bars: list[Bar], lookback: int = 20) -> float:
    if not bars:
        return 0.0
    sample = bars[-lookback:]
    volumes = [b.tick_volume or 1 for b in sample]
    return sum(volumes) / len(volumes)


def buyer_absorption(bar: Bar, avg_vol: float, min_wick_ratio: float = 1.2) -> bool:
    """Heavy buying in upper wick without follow-through body expansion."""
    if not bar.is_bullish:
        return False
    body = max(bar.body_size, 1e-9)
    if bar.upper_wick < body * min_wick_ratio:
        return False
    vol = bar.tick_volume or 0
    return vol >= avg_vol * 1.5


def seller_absorption(bar: Bar, avg_vol: float, min_wick_ratio: float = 1.2) -> bool:
    """Heavy selling in lower wick without follow-through body expansion."""
    if not bar.is_bearish:
        return False
    body = max(bar.body_size, 1e-9)
    if bar.lower_wick < body * min_wick_ratio:
        return False
    vol = bar.tick_volume or 0
    return vol >= avg_vol * 1.5


def recent_swing_low(bars: list[Bar], lookback: int = 8) -> float:
    sample = bars[-lookback:]
    return min(b.low for b in sample) if sample else 0.0


def recent_swing_high(bars: list[Bar], lookback: int = 8) -> float:
    sample = bars[-lookback:]
    return max(b.high for b in sample) if sample else 0.0
