"""VP orderflow absorption helpers."""

from __future__ import annotations

from backtester.core import Bar
from backtester.indicators.volume_profile import VolumeProfile


def is_near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def near_upper_reference(bar: Bar, profile: VolumeProfile) -> bool:
    return any(
        is_near_level(bar.high, level)
        for level in (profile.vah, profile.poc, profile.vwap)
    )


def below_value_area(bar: Bar, profile: VolumeProfile) -> bool:
    return bar.close < profile.val
