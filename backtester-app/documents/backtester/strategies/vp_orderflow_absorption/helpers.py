"""Strategy-specific helpers for VP orderflow absorption."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionEvent:
    direction: str
    level: float
    wick_extreme: float
    bar_time: str


def is_buyer_absorption(bar: Bar, min_wick_body_ratio: float = 1.5, volume_threshold: int = 0) -> bool:
    """Proxy for buyer absorption: heavy upper wick, weak close, elevated volume."""
    if bar.body_size <= 0:
        return False
    if bar.upper_wick / bar.body_size < min_wick_body_ratio:
        return False
    if volume_threshold > 0 and (bar.tick_volume or 0) < volume_threshold:
        return False
    return bar.close <= bar.body_high


def is_seller_absorption(bar: Bar, min_wick_body_ratio: float = 1.5, volume_threshold: int = 0) -> bool:
    """Proxy for seller absorption: heavy lower wick, weak close, elevated volume."""
    if bar.body_size <= 0:
        return False
    if bar.lower_wick / bar.body_size < min_wick_body_ratio:
        return False
    if volume_threshold > 0 and (bar.tick_volume or 0) < volume_threshold:
        return False
    return bar.close >= bar.body_low


def near_level(price: float, level: float, tolerance_pct: float) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def volume_threshold_from_history(bars: list[Bar], percentile: float) -> int:
    volumes = sorted((bar.tick_volume or 0) for bar in bars if bar.tick_volume)
    if not volumes:
        return 0
    idx = int(len(volumes) * percentile / 100.0)
    idx = min(max(idx, 0), len(volumes) - 1)
    return volumes[idx]
