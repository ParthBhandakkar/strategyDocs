"""Strategy-specific helpers for VP orderflow absorption."""

from __future__ import annotations

from backtester.core import Bar
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


def near_level(price: float, level: float, tolerance_pct: float) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def price_above_val(price: float, profile: VolumeProfile) -> bool:
    return price > profile.val


def price_below_vah(price: float, profile: VolumeProfile) -> bool:
    return price < profile.vah


def build_session_profile(session_bars: list[Bar]) -> VolumeProfile | None:
    if len(session_bars) < 20:
        return None
    return compute_frvp(session_bars, row_size=80, va_pct=70.0)
