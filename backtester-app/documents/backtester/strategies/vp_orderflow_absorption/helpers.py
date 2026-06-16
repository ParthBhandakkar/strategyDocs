"""Strategy-specific helpers for VP orderflow absorption setups."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionEvent:
    direction: str
    bar_index: int
    cluster_level: float
    absorption_high: float
    absorption_low: float


def average_volume(bars: list[Bar], lookback: int = 20) -> float:
    if not bars:
        return 0.0
    sample = bars[-lookback:]
    volumes = [b.tick_volume or 1 for b in sample]
    return sum(volumes) / len(volumes)


def detect_upper_wick_absorption(
    bar: Bar,
    avg_vol: float,
    min_wick_ratio: float = 0.35,
    min_volume_ratio: float = 1.2,
) -> bool:
    """Proxy for buyer absorption at highs: heavy activity in upper wick, weak close."""
    total_range = bar.total_range
    if total_range <= 0:
        return False
    wick_ratio = bar.upper_wick / total_range
    vol = bar.tick_volume or 1
    if wick_ratio < min_wick_ratio:
        return False
    if avg_vol > 0 and vol < avg_vol * min_volume_ratio:
        return False
    return bar.close <= bar.body_high and bar.close <= bar.open


def detect_lower_wick_absorption(
    bar: Bar,
    avg_vol: float,
    min_wick_ratio: float = 0.35,
    min_volume_ratio: float = 1.2,
) -> bool:
    """Proxy for seller absorption at lows: heavy activity in lower wick, weak breakdown."""
    total_range = bar.total_range
    if total_range <= 0:
        return False
    wick_ratio = bar.lower_wick / total_range
    vol = bar.tick_volume or 1
    if wick_ratio < min_wick_ratio:
        return False
    if avg_vol > 0 and vol < avg_vol * min_volume_ratio:
        return False
    return bar.close >= bar.body_low and bar.close >= bar.open


def find_support_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Recent local support cluster from swing lows in lookback window."""
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    lows = [b.low for b in window]
    return min(lows)


def find_resistance_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    highs = [b.high for b in window]
    return max(highs)
