"""
Strategy-only helpers for VP + orderflow absorption detection.
Uses tick_volume in wicks as an orderflow proxy (no L2 data in backtest).
"""

from __future__ import annotations

from backtester.core import Bar
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


def compute_session_vwap(bars: list[Bar]) -> float | None:
    if not bars:
        return None
    total_volume = 0
    weighted = 0.0
    for bar in bars:
        vol = bar.tick_volume or 1
        typical = (bar.high + bar.low + bar.close) / 3.0
        weighted += typical * vol
        total_volume += vol
    if total_volume <= 0:
        return None
    return weighted / total_volume


def wick_volume_share(bar: Bar, upper: bool) -> float:
    vol = bar.tick_volume or 0
    if vol <= 0 or bar.total_range <= 0:
        return 0.0
    wick = bar.upper_wick if upper else bar.lower_wick
    body = max(bar.body_size, bar.total_range * 0.05)
    wick_fraction = wick / bar.total_range
    body_fraction = body / bar.total_range
    if body_fraction <= 0:
        return 0.0
    return (wick_fraction / body_fraction) * vol


def is_buyer_absorption(bar: Bar, min_wick_volume_ratio: float, min_tick_volume: int) -> bool:
    if bar.tick_volume < min_tick_volume:
        return False
    if bar.upper_wick <= bar.body_size:
        return False
    upper_share = wick_volume_share(bar, upper=True)
    return upper_share >= min_tick_volume * min_wick_volume_ratio


def is_seller_absorption(bar: Bar, min_wick_volume_ratio: float, min_tick_volume: int) -> bool:
    if bar.tick_volume < min_tick_volume:
        return False
    if bar.lower_wick <= bar.body_size:
        return False
    lower_share = wick_volume_share(bar, upper=False)
    return lower_share >= min_tick_volume * min_wick_volume_ratio


def near_level(price: float, level: float, tolerance_pct: float) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def recent_cluster_low(bars: list[Bar], lookback: int) -> float | None:
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    return min(bar.low for bar in window)


def recent_cluster_high(bars: list[Bar], lookback: int) -> float | None:
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    return max(bar.high for bar in window)


def developing_vp(bars: list[Bar]) -> VolumeProfile | None:
    return compute_frvp(bars, row_size=80, va_pct=70.0)
