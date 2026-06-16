"""VP orderflow absorption helpers."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionEvent:
    direction: str
    cluster_high: float
    cluster_low: float
    reference_bar_time: object


def average_tick_volume(bars: list[Bar], lookback: int = 20) -> float:
    if not bars:
        return 0.0
    sample = bars[-lookback:]
    total = sum(bar.tick_volume or 0 for bar in sample)
    return total / max(len(sample), 1)


def detect_buyer_absorption(bar: Bar, avg_volume: float, min_ratio: float = 1.5) -> bool:
    if not bar.is_bullish:
        return False
    if bar.upper_wick <= bar.body_size:
        return False
    volume = bar.tick_volume or 0
    return volume >= avg_volume * min_ratio and bar.close <= bar.open + bar.body_size * 0.35


def detect_seller_absorption(bar: Bar, avg_volume: float, min_ratio: float = 1.5) -> bool:
    if not bar.is_bearish:
        return False
    if bar.lower_wick <= bar.body_size:
        return False
    volume = bar.tick_volume or 0
    return volume >= avg_volume * min_ratio and bar.close >= bar.open - bar.body_size * 0.35


def local_support_level(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < lookback:
        return None
    sample = bars[-lookback:]
    return min(bar.low for bar in sample)


def local_resistance_level(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < lookback:
        return None
    sample = bars[-lookback:]
    return max(bar.high for bar in sample)


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct
