"""Strategy-specific helpers for VP orderflow absorption."""

from __future__ import annotations

from backtester.core import Bar
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


def developing_session_vp(d1_bars: list[Bar], m1_bars: list[Bar]) -> VolumeProfile | None:
    """Build developing VP from intraday session M1 bars with D1 context."""
    if len(m1_bars) < 10:
        return None
    session_bars = m1_bars[-90:]
    if d1_bars:
        session_bars = [d1_bars[-1]] + session_bars
    return compute_frvp(session_bars, row_size=40, va_pct=70.0)


def in_upper_value(bar: Bar, vp: VolumeProfile, tolerance: float) -> bool:
    return bar.high >= vp.poc and abs(bar.high - vp.vah) <= tolerance * 4


def in_lower_value(bar: Bar, vp: VolumeProfile, tolerance: float) -> bool:
    return bar.low <= vp.poc and abs(bar.low - vp.val) <= tolerance * 4
