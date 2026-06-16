"""
Strategy-only helpers for VP + orderflow absorption detection.
Uses tick_volume as proxy for orderflow aggression (no L2 data in CSV).
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.volume_profile import VolumeProfile


@dataclass
class AbsorptionSignal:
    direction: str  # "buyer" or "seller"
    bar: Bar
    cluster_low: float
    cluster_high: float


def session_bars_for_day(bars: list[Bar], current_time) -> list[Bar]:
    """M1 bars from NY 9:30 open through current_time on same NY date."""
    ny_date = get_ny_time(current_time).date()
    result = []
    for bar in bars:
        ny = get_ny_time(bar.time)
        if ny.date() != ny_date:
            continue
        if ny.time().hour > 9 or (ny.time().hour == 9 and ny.time().minute >= 30):
            if bar.time <= current_time:
                result.append(bar)
    return result


def detect_wick_absorption(bar: Bar, min_wick_vol_ratio: float = 0.55) -> str | None:
    """
    Wick absorption: heavy volume in wick without body follow-through.
    Returns 'buyer' (upper wick) or 'seller' (lower wick) or None.
    """
    vol = bar.tick_volume or 1
    if bar.total_range <= 0:
        return None

    upper_ratio = bar.upper_wick / bar.total_range
    lower_ratio = bar.lower_wick / bar.total_range

    if upper_ratio >= min_wick_vol_ratio and bar.close <= bar.body_high:
        return "buyer"
    if lower_ratio >= min_wick_vol_ratio and bar.close >= bar.body_low:
        return "seller"
    return None


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def is_near_vah_zone(price: float, vp: VolumeProfile, tolerance_pct: float = 0.0015) -> bool:
    return (
        near_level(price, vp.vah, tolerance_pct)
        or near_level(price, vp.poc, tolerance_pct)
        or near_level(price, vp.vwap, tolerance_pct)
    )


def is_below_val(price: float, vp: VolumeProfile) -> bool:
    return price < vp.val


def find_support_cluster(bars: list[Bar], lookback: int = 8) -> tuple[float, float]:
    """Recent swing low cluster for inversion trigger."""
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    if not recent:
        return 0.0, 0.0
    lows = [b.low for b in recent]
    cluster_low = min(lows)
    cluster_high = max(b.close for b in recent if b.low <= cluster_low * 1.0002)
    return cluster_low, cluster_high or cluster_low


def find_resistance_cluster(bars: list[Bar], lookback: int = 8) -> tuple[float, float]:
    """Recent swing high cluster for inversion trigger."""
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    if not recent:
        return 0.0, 0.0
    highs = [b.high for b in recent]
    cluster_high = max(highs)
    cluster_low = min(b.close for b in recent if b.high >= cluster_high * 0.9998)
    return cluster_low or cluster_high, cluster_high
