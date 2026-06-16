"""
Orderflow approximations using tick volume when L2 data is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str  # "buyer_absorption" or "seller_absorption"
    bar_index: int
    cluster_price: float
    wick_volume_ratio: float


def wick_volume_share(bar: Bar) -> tuple[float, float, float]:
    """Estimate volume share in upper wick, body, lower wick."""
    total = float(bar.tick_volume or 1)
    if bar.total_range <= 0:
        return 0.0, 1.0, 0.0
    upper = bar.upper_wick / bar.total_range
    lower = bar.lower_wick / bar.total_range
    body = max(0.0, 1.0 - upper - lower)
    return upper, body, lower


def detect_wick_absorption(
    bar: Bar,
    min_wick_ratio: float = 0.35,
    min_volume: int = 50,
) -> str | None:
    """
    Wick absorption: heavy volume in wick without directional follow-through.
    Returns buyer_absorption (upper wick) or seller_absorption (lower wick).
    """
    if (bar.tick_volume or 0) < min_volume:
        return None
    upper_share, body_share, lower_share = wick_volume_share(bar)
    if upper_share >= min_wick_ratio and bar.upper_wick > bar.body_size:
        if not bar.is_bullish or bar.close <= bar.open + bar.body_size * 0.3:
            return "buyer_absorption"
    if lower_share >= min_wick_ratio and bar.lower_wick > bar.body_size:
        if not bar.is_bearish or bar.close >= bar.open - bar.body_size * 0.3:
            return "seller_absorption"
    return None


def find_volume_cluster_level(bars: list[Bar], lookback: int = 8) -> tuple[float | None, float | None]:
    """
    Recent support (low cluster) and resistance (high cluster) from swing extremes
    with elevated tick volume.
    """
    if len(bars) < 3:
        return None, None
    window = bars[-lookback:]
    support = min(window, key=lambda b: b.low)
    resistance = max(window, key=lambda b: b.high)
    avg_vol = sum(b.tick_volume or 0 for b in window) / len(window)
    support_level = support.low if (support.tick_volume or 0) >= avg_vol else None
    resistance_level = resistance.high if (resistance.tick_volume or 0) >= avg_vol else None
    return support_level, resistance_level
