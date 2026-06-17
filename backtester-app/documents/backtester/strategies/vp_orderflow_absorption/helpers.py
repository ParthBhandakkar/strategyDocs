"""VP + orderflow absorption helpers."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class OrderCluster:
    level: float
    direction: str
    source_bar_time: str


def average_volume(bars: list[Bar], lookback: int = 20) -> float:
    if not bars:
        return 0.0
    sample = bars[-lookback:]
    volumes = [bar.tick_volume or 1 for bar in sample]
    return sum(volumes) / len(volumes)


def is_high_volume_bar(bar: Bar, avg_volume: float, multiplier: float = 1.5) -> bool:
    return (bar.tick_volume or 1) >= max(1.0, avg_volume * multiplier)


def detect_buyer_absorption(bar: Bar, avg_volume: float) -> bool:
    """Heavy aggression at highs without upward follow-through."""
    if bar.total_range <= 0:
        return False
    if not is_high_volume_bar(bar, avg_volume):
        return False
    upper_wick_ratio = bar.upper_wick / max(bar.body_size, bar.total_range * 0.05)
    stalled_close = bar.close <= bar.high - (bar.total_range * 0.25)
    return upper_wick_ratio >= 1.2 and stalled_close


def detect_seller_absorption(bar: Bar, avg_volume: float) -> bool:
    """Heavy aggression at lows without downward follow-through."""
    if bar.total_range <= 0:
        return False
    if not is_high_volume_bar(bar, avg_volume):
        return False
    lower_wick_ratio = bar.lower_wick / max(bar.body_size, bar.total_range * 0.05)
    stalled_close = bar.close >= bar.low + (bar.total_range * 0.25)
    return lower_wick_ratio >= 1.2 and stalled_close


def find_support_cluster(bars: list[Bar], lookback: int = 8) -> OrderCluster | None:
    """Recent high-volume support from aggressive buy clusters."""
    if len(bars) < 2:
        return None
    sample = bars[-lookback:]
    avg_volume = average_volume(sample)
    candidates = [
        bar
        for bar in sample[:-1]
        if is_high_volume_bar(bar, avg_volume) and bar.is_bullish
    ]
    if not candidates:
        return None
    cluster_bar = min(candidates, key=lambda bar: bar.body_low)
    return OrderCluster(
        level=cluster_bar.body_low,
        direction="support",
        source_bar_time=cluster_bar.time.isoformat(),
    )


def find_resistance_cluster(bars: list[Bar], lookback: int = 8) -> OrderCluster | None:
    """Recent high-volume resistance from aggressive sell clusters."""
    if len(bars) < 2:
        return None
    sample = bars[-lookback:]
    avg_volume = average_volume(sample)
    candidates = [
        bar
        for bar in sample[:-1]
        if is_high_volume_bar(bar, avg_volume) and bar.is_bearish
    ]
    if not candidates:
        return None
    cluster_bar = max(candidates, key=lambda bar: bar.body_high)
    return OrderCluster(
        level=cluster_bar.body_high,
        direction="resistance",
        source_bar_time=cluster_bar.time.isoformat(),
    )


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct
