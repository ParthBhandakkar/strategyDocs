"""
Developing session volume profile and orderflow absorption proxies.
Tick volume substitutes for L2 orderflow when footprint data is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


@dataclass
class AbsorptionSignal:
    direction: str  # "buyer" or "seller"
    bar_index: int
    wick_high: float
    wick_low: float
    cluster_price: float


def session_vwap(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    total_vol = 0
    weighted = 0.0
    for bar in bars:
        vol = max(bar.tick_volume, 1)
        typical = (bar.high + bar.low + bar.close) / 3.0
        weighted += typical * vol
        total_vol += vol
    return weighted / total_vol if total_vol else bars[-1].close


def developing_vp(bars: list[Bar]) -> VolumeProfile | None:
    return compute_frvp(bars, row_size=80, va_pct=70.0)


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """Return (upper_wick_vol_share, lower_wick_vol_share) using tick_volume."""
    vol = max(bar.tick_volume, 1)
    total_range = max(bar.total_range, 1e-9)
    upper_share = bar.upper_wick / total_range
    lower_share = bar.lower_wick / total_range
    body_share = max(0.0, 1.0 - upper_share - lower_share)
    return upper_share * vol, lower_share * vol + body_share * vol * 0.25


def detect_buyer_absorption(bar: Bar, min_wick_share: float = 0.45) -> bool:
    """Heavy buying in upper wick without close near high — absorption proxy."""
    if bar.total_range <= 0:
        return False
    upper_vol, _ = wick_volume_ratio(bar)
    vol = max(bar.tick_volume, 1)
    upper_share = upper_vol / vol
    close_not_at_high = bar.close < bar.high - bar.total_range * 0.15
    return upper_share >= min_wick_share and close_not_at_high and bar.is_bullish


def detect_seller_absorption(bar: Bar, min_wick_share: float = 0.45) -> bool:
    """Heavy selling in lower wick without close near low — absorption proxy."""
    if bar.total_range <= 0:
        return False
    _, lower_vol = wick_volume_ratio(bar)
    vol = max(bar.tick_volume, 1)
    lower_share = lower_vol / vol
    close_not_at_low = bar.close > bar.low + bar.total_range * 0.15
    return lower_share >= min_wick_share and close_not_at_low and bar.is_bearish


def find_support_cluster(bars: list[Bar], lookback: int = 12) -> float | None:
    """Recent swing low with elevated tick volume — order cluster proxy."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    avg_vol = sum(max(b.tick_volume, 1) for b in window) / len(window)
    best_low = None
    best_vol = 0
    for i in range(1, len(window) - 1):
        prev_bar = window[i - 1]
        bar = window[i]
        next_bar = window[i + 1]
        if bar.low <= prev_bar.low and bar.low <= next_bar.low:
            vol = max(bar.tick_volume, 1)
            if vol >= avg_vol * 1.2 and vol > best_vol:
                best_vol = vol
                best_low = bar.low
    return best_low


def find_resistance_cluster(bars: list[Bar], lookback: int = 12) -> float | None:
    """Recent swing high with elevated tick volume."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    avg_vol = sum(max(b.tick_volume, 1) for b in window) / len(window)
    best_high = None
    best_vol = 0
    for i in range(1, len(window) - 1):
        prev_bar = window[i - 1]
        bar = window[i]
        next_bar = window[i + 1]
        if bar.high >= prev_bar.high and bar.high >= next_bar.high:
            vol = max(bar.tick_volume, 1)
            if vol >= avg_vol * 1.2 and vol > best_vol:
                best_vol = vol
                best_high = bar.high
    return best_high


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct
