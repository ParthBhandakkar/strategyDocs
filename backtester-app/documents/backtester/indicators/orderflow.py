"""
Orderflow absorption proxies using tick_volume in candle wicks.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str  # "buyer_absorption" or "seller_absorption"
    bar: Bar
    wick_extreme: float
    cluster_level: float


def _wick_volume_share(bar: Bar) -> tuple[float, float]:
    total = max(bar.tick_volume, 1)
    body = max(bar.body_size, 1e-9)
    upper = max(bar.upper_wick, 0.0)
    lower = max(bar.lower_wick, 0.0)
    wick_total = upper + lower
    if wick_total <= 0:
        return 0.0, 0.0
    upper_share = (upper / wick_total) * (bar.tick_volume / total)
    lower_share = (lower / wick_total) * (bar.tick_volume / total)
    return upper_share, lower_share


def detect_buyer_absorption(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    """
    Heavy aggression at highs without upward follow-through.
    Proxy: large upper wick, close in lower half of range, elevated tick volume.
    """
    if bar.total_range <= 0:
        return False
    upper_share, _ = _wick_volume_share(bar)
    close_position = (bar.close - bar.low) / bar.total_range
    wick_ratio = bar.upper_wick / bar.total_range
    return (
        wick_ratio >= min_wick_ratio
        and close_position <= 0.55
        and bar.tick_volume > 0
        and upper_share > 0.25
    )


def detect_seller_absorption(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    """Heavy selling at lows without downward follow-through."""
    if bar.total_range <= 0:
        return False
    _, lower_share = _wick_volume_share(bar)
    close_position = (bar.close - bar.low) / bar.total_range
    wick_ratio = bar.lower_wick / bar.total_range
    return (
        wick_ratio >= min_wick_ratio
        and close_position >= 0.45
        and bar.tick_volume > 0
        and lower_share > 0.25
    )


def nearest_swing_cluster(bars: list[Bar], lookback: int = 8) -> tuple[float, float]:
    """Return recent local support (swing low) and resistance (swing high) clusters."""
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if not window:
        return 0.0, 0.0
    support = min(b.low for b in window[:-1]) if len(window) > 1 else window[-1].low
    resistance = max(b.high for b in window[:-1]) if len(window) > 1 else window[-1].high
    return support, resistance
