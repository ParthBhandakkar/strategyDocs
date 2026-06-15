"""
Developing session volume profile helpers for VP + orderflow strategies.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


@dataclass
class DevelopingVPLevels:
    poc: float
    vah: float
    val: float
    vwap: float
    total_volume: int


def compute_vwap(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    weighted = 0.0
    volume = 0
    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / 3.0
        vol = bar.tick_volume or 1
        weighted += typical * vol
        volume += vol
    if volume <= 0:
        return bars[-1].close
    return weighted / volume


def compute_developing_vp(bars: list[Bar]) -> DevelopingVPLevels | None:
    if len(bars) < 5:
        return None
    profile = compute_frvp(bars)
    if profile is None:
        return None
    return DevelopingVPLevels(
        poc=profile.poc,
        vah=profile.vah,
        val=profile.val,
        vwap=compute_vwap(bars),
        total_volume=profile.total_volume,
    )


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """Return upper-wick and lower-wick volume share proxies using tick volume."""
    volume = float(bar.tick_volume or 1)
    total_range = max(bar.total_range, 1e-9)
    upper_share = bar.upper_wick / total_range
    lower_share = bar.lower_wick / total_range
    return upper_share * volume, lower_share * volume


def is_buyer_absorption_at_high(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    if bar.total_range <= 0:
        return False
    upper_wick_ratio = bar.upper_wick / bar.total_range
    return upper_wick_ratio >= min_wick_ratio and bar.close <= bar.body_high


def is_seller_absorption_at_low(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    if bar.total_range <= 0:
        return False
    lower_wick_ratio = bar.lower_wick / bar.total_range
    return lower_wick_ratio >= min_wick_ratio and bar.close >= bar.body_low


def recent_support_cluster(history: list[Bar], lookback: int = 8) -> float | None:
    if len(history) < 3:
        return None
    window = history[-lookback:]
    lows = sorted(bar.low for bar in window)
    return lows[1] if len(lows) > 1 else lows[0]


def recent_resistance_cluster(history: list[Bar], lookback: int = 8) -> float | None:
    if len(history) < 3:
        return None
    window = history[-lookback:]
    highs = sorted((bar.high for bar in window), reverse=True)
    return highs[1] if len(highs) > 1 else highs[0]
