"""Absorption and order-cluster helpers for VP orderflow strategy."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str
    absorption_high: float
    absorption_low: float
    cluster_level: float


def average_volume(bars: list[Bar], lookback: int = 20) -> float:
    if not bars:
        return 0.0
    sample = bars[-lookback:]
    return sum(bar.tick_volume or 1 for bar in sample) / len(sample)


def buyer_absorption_at_wick(bar: Bar, avg_vol: float, min_wick_ratio: float = 0.45) -> bool:
    if bar.total_range <= 0:
        return False
    upper_ratio = bar.upper_wick / bar.total_range
    volume = bar.tick_volume or 1
    stalled = bar.close <= bar.body_high - (bar.body_size * 0.25)
    return upper_ratio >= min_wick_ratio and volume >= avg_vol * 1.5 and bar.is_bullish and stalled


def seller_absorption_at_wick(bar: Bar, avg_vol: float, min_wick_ratio: float = 0.45) -> bool:
    if bar.total_range <= 0:
        return False
    lower_ratio = bar.lower_wick / bar.total_range
    volume = bar.tick_volume or 1
    stalled = bar.close >= bar.body_low + (bar.body_size * 0.25)
    return lower_ratio >= min_wick_ratio and volume >= avg_vol * 1.5 and bar.is_bearish and stalled


def nearest_support_cluster(bars: list[Bar], lookback: int = 8) -> float:
    sample = bars[-lookback:]
    return min(bar.low for bar in sample) if sample else 0.0


def nearest_resistance_cluster(bars: list[Bar], lookback: int = 8) -> float:
    sample = bars[-lookback:]
    return max(bar.high for bar in sample) if sample else 0.0


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct
