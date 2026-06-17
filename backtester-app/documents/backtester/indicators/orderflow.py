"""
Orderflow proxies using tick_volume and wick structure.
Approximates L2 absorption when real orderflow depth is unavailable.
"""

from __future__ import annotations

from backtester.core import Bar


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """Return (upper_wick_vol_share, lower_wick_vol_share) as fractions of tick_volume."""
    vol = max(bar.tick_volume, 1)
    total_range = max(bar.total_range, 1e-9)
    upper_share = bar.upper_wick / total_range
    lower_share = bar.lower_wick / total_range
    return upper_share * vol, lower_share * vol


def is_buyer_absorption(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    """
    Heavy aggressive buying trapped in upper wick without body follow-through.
    Proxy: large upper wick, bearish or small bullish body, elevated tick_volume.
    """
    if bar.total_range <= 0:
        return False
    upper_frac = bar.upper_wick / bar.total_range
    body_frac = bar.body_size / bar.total_range
    return (
        upper_frac >= min_wick_ratio
        and body_frac <= 0.45
        and bar.tick_volume >= 50
    )


def is_seller_absorption(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    """Heavy aggressive selling trapped in lower wick without downside follow-through."""
    if bar.total_range <= 0:
        return False
    lower_frac = bar.lower_wick / bar.total_range
    body_frac = bar.body_size / bar.total_range
    return (
        lower_frac >= min_wick_ratio
        and body_frac <= 0.45
        and bar.tick_volume >= 50
    )


def compute_vwap(bars: list[Bar]) -> float | None:
    """Session VWAP from typical price weighted by tick_volume."""
    if not bars:
        return None
    total_vol = 0
    weighted = 0.0
    for bar in bars:
        vol = max(bar.tick_volume, 1)
        typical = (bar.high + bar.low + bar.close) / 3.0
        weighted += typical * vol
        total_vol += vol
    if total_vol <= 0:
        return None
    return weighted / total_vol
