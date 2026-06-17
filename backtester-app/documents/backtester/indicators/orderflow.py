"""
Orderflow approximations using tick volume (no L2 depth).
"""

from __future__ import annotations

from backtester.core import Bar


def wick_volume_ratio(bar: Bar, side: str) -> float:
    """Share of bar range attributed to upper or lower wick."""
    total = bar.total_range
    if total <= 0:
        return 0.0
    if side == "upper":
        return bar.upper_wick / total
    return bar.lower_wick / total


def is_buyer_absorption(
    bar: Bar,
    avg_volume: float,
    min_wick_ratio: float = 0.45,
    min_volume_mult: float = 1.5,
) -> bool:
    """
    Heavy activity in upper wick without bullish follow-through.
    Proxy for aggressive buyers absorbed at highs.
    """
    if avg_volume <= 0:
        return False
    if bar.tick_volume < avg_volume * min_volume_mult:
        return False
    if wick_volume_ratio(bar, "upper") < min_wick_ratio:
        return False
    return bar.close <= bar.body_high


def is_seller_absorption(
    bar: Bar,
    avg_volume: float,
    min_wick_ratio: float = 0.45,
    min_volume_mult: float = 1.5,
) -> bool:
    """Heavy activity in lower wick without bearish follow-through."""
    if avg_volume <= 0:
        return False
    if bar.tick_volume < avg_volume * min_volume_mult:
        return False
    if wick_volume_ratio(bar, "lower") < min_wick_ratio:
        return False
    return bar.close >= bar.body_low


def session_vwap(bars: list[Bar]) -> float:
    """Volume-weighted average price for a bar list."""
    total_vol = 0
    weighted = 0.0
    for bar in bars:
        vol = bar.tick_volume or 1
        typical = (bar.high + bar.low + bar.close) / 3.0
        weighted += typical * vol
        total_vol += vol
    if total_vol <= 0:
        return bars[-1].close if bars else 0.0
    return weighted / total_vol
