"""
Strategy-specific helpers for VP + orderflow absorption.
Uses tick_volume as an orderflow proxy (no L2 data in CSV history).
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


@dataclass
class AbsorptionEvent:
    direction: str  # "buyer" or "seller"
    bar_index: int
    cluster_low: float
    cluster_high: float
    wick_high: float
    wick_low: float


def developing_session_bars(day_bars: list[Bar]) -> list[Bar]:
    """Bars from NY 9:30 onward for the current session day."""
    return list(day_bars)


def compute_developing_vp(bars: list[Bar]) -> VolumeProfile | None:
    """Compute developing volume profile from session bars."""
    if len(bars) < 30:
        return None
    return compute_frvp(bars, row_size=80, va_pct=70.0)


def vwap_from_bars(bars: list[Bar]) -> float | None:
    """Volume-weighted average price for session bars."""
    total_vol = 0
    weighted = 0.0
    for bar in bars:
        vol = bar.tick_volume or 1
        typical = (bar.high + bar.low + bar.close) / 3.0
        weighted += typical * vol
        total_vol += vol
    if total_vol <= 0:
        return None
    return weighted / total_vol


def average_volume(bars: list[Bar], lookback: int = 20) -> float:
    if not bars:
        return 0.0
    sample = bars[-lookback:]
    return sum(b.tick_volume or 0 for b in sample) / len(sample)


def detect_buyer_absorption_at_highs(bar: Bar, avg_vol: float) -> bool:
    """
  Buyer absorption: heavy volume in upper wick with weak bullish follow-through.
  Wick volume proxy per video spec (wick vs body rule).
  """
    if bar.total_range <= 0:
        return False
    upper_ratio = bar.upper_wick / bar.total_range
    body_ratio = bar.body_size / bar.total_range
    vol = bar.tick_volume or 0
    if upper_ratio < 0.35:
        return False
    if body_ratio > 0.45:
        return False
    if vol < avg_vol * 1.5:
        return False
    # Price stalled: close not near high despite upper-wick aggression
    if bar.close >= bar.high - bar.total_range * 0.15:
        return False
    return True


def detect_seller_absorption_at_lows(bar: Bar, avg_vol: float) -> bool:
    """Seller absorption: heavy volume in lower wick without further downside."""
    if bar.total_range <= 0:
        return False
    lower_ratio = bar.lower_wick / bar.total_range
    body_ratio = bar.body_size / bar.total_range
    vol = bar.tick_volume or 0
    if lower_ratio < 0.35:
        return False
    if body_ratio > 0.45:
        return False
    if vol < avg_vol * 1.5:
        return False
    if bar.close <= bar.low + bar.total_range * 0.15:
        return False
    return True


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def recent_swing_low(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    return min(b.low for b in window)


def recent_swing_high(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    return max(b.high for b in window)
