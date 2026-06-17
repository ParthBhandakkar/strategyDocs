"""
Orderflow absorption proxies using OHLCV tick_volume (no L2 depth).
Approximates wick absorption and order-cluster levels for backtesting.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.structure import detect_swing_highs, detect_swing_lows


@dataclass
class AbsorptionSignal:
    """Detected absorption at a wick extreme."""
    bar_index: int
    direction: str  # "buyer_absorption" (bearish bias) or "seller_absorption" (bullish bias)
    wick_high: float
    wick_low: float
    cluster_level: float
    volume_ratio: float


def wick_volume_share(bar: Bar, side: str) -> float:
    """Share of bar range attributed to upper or lower wick."""
    total = bar.total_range
    if total <= 0:
        return 0.0
    if side == "upper":
        return bar.upper_wick / total
    return bar.lower_wick / total


def is_buyer_absorption(bar: Bar, avg_volume: float, min_wick_ratio: float = 0.45) -> bool:
    """
    Bullish candle with heavy upper-wick volume share — buyers absorbed at highs.
    Proxy for aggressive buy orders failing at the wick.
    """
    if not bar.is_bullish or avg_volume <= 0:
        return False
    wick_share = wick_volume_share(bar, "upper")
    vol_spike = bar.tick_volume >= avg_volume * 1.2
    return wick_share >= min_wick_ratio and vol_spike


def is_seller_absorption(bar: Bar, avg_volume: float, min_wick_ratio: float = 0.45) -> bool:
    """Bearish candle with heavy lower-wick volume share — sellers absorbed at lows."""
    if not bar.is_bearish or avg_volume <= 0:
        return False
    wick_share = wick_volume_share(bar, "lower")
    vol_spike = bar.tick_volume >= avg_volume * 1.2
    return wick_share >= min_wick_ratio and vol_spike


def average_volume(bars: list[Bar], lookback: int = 20) -> float:
    if not bars:
        return 0.0
    window = bars[-lookback:]
    volumes = [b.tick_volume for b in window if b.tick_volume > 0]
    if not volumes:
        return 1.0
    return sum(volumes) / len(volumes)


def nearest_support_cluster(bars: list[Bar], lookback: int = 15) -> float | None:
    """Recent swing-low cluster acting as close-proximity support."""
    if len(bars) < lookback + 3:
        return None
    window = bars[-lookback:]
    lows = detect_swing_lows(window, lookback=2)
    if lows:
        return min(s.price for s in lows[-3:])
    return min(b.low for b in window[-5:])


def nearest_resistance_cluster(bars: list[Bar], lookback: int = 15) -> float | None:
    """Recent swing-high cluster acting as close-proximity resistance."""
    if len(bars) < lookback + 3:
        return None
    window = bars[-lookback:]
    highs = detect_swing_highs(window, lookback=2)
    if highs:
        return max(s.price for s in highs[-3:])
    return max(b.high for b in window[-5:])


def detect_absorption_at_level(
    bar: Bar,
    bars: list[Bar],
    level: float,
    side: str,
    tolerance_pct: float = 0.0015,
) -> bool:
    """
    Check if bar shows absorption near a VP level (VAH/VAL/POC/VWAP).
    side: "above" for short setups near VAH, "below" for long setups near VAL.
    """
    if level <= 0:
        return False
    tol = level * tolerance_pct
    avg_vol = average_volume(bars)
    if side == "above":
        near_level = bar.high >= level - tol
        return near_level and is_buyer_absorption(bar, avg_vol)
    near_level = bar.low <= level + tol
    return near_level and is_seller_absorption(bar, avg_vol)
