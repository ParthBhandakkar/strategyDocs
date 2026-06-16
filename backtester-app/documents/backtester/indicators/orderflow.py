"""
Orderflow proxies using tick_volume on OHLCV bars (no L2 depth).
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str  # "buyer_absorption" | "seller_absorption"
    bar_index: int
    cluster_level: float
    wick_extreme: float


def wick_volume_share(bar: Bar) -> tuple[float, float]:
    """Return (upper_wick_share, lower_wick_share) of tick volume."""
    vol = max(bar.tick_volume, 1)
    total_range = max(bar.total_range, 1e-9)
    upper_share = bar.upper_wick / total_range
    lower_share = bar.lower_wick / total_range
    return upper_share * vol, lower_share * vol


def detect_buyer_absorption(
    bar: Bar,
    min_wick_ratio: float = 0.45,
    min_volume: int = 50,
) -> bool:
    """Heavy volume in upper wick with limited upward follow-through."""
    if bar.total_range <= 0:
        return False
    wick_ratio = bar.upper_wick / bar.total_range
    return (
        wick_ratio >= min_wick_ratio
        and bar.tick_volume >= min_volume
        and bar.upper_wick > bar.body_size
    )


def detect_seller_absorption(
    bar: Bar,
    min_wick_ratio: float = 0.45,
    min_volume: int = 50,
) -> bool:
    """Heavy volume in lower wick with limited downward follow-through."""
    if bar.total_range <= 0:
        return False
    wick_ratio = bar.lower_wick / bar.total_range
    return (
        wick_ratio >= min_wick_ratio
        and bar.tick_volume >= min_volume
        and bar.lower_wick > bar.body_size
    )


def compute_session_vwap(bars: list[Bar]) -> float:
    """Volume-weighted average price for a bar window."""
    total_vol = 0
    weighted = 0.0
    for bar in bars:
        vol = max(bar.tick_volume, 1)
        typical = (bar.high + bar.low + bar.close) / 3.0
        weighted += typical * vol
        total_vol += vol
    if total_vol <= 0:
        return bars[-1].close if bars else 0.0
    return weighted / total_vol


def recent_support_cluster(bars: list[Bar], lookback: int = 5) -> float:
    """Proxy for close-proximity support: lowest low of recent window."""
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if not window:
        return 0.0
    return min(b.low for b in window)


def recent_resistance_cluster(bars: list[Bar], lookback: int = 5) -> float:
    """Proxy for close-proximity resistance: highest high of recent window."""
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if not window:
        return 0.0
    return max(b.high for b in window)
