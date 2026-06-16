"""Volume profile helpers including session VWAP."""

from __future__ import annotations

from backtester.core import Bar
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


def compute_vwap(bars: list[Bar]) -> float | None:
    if not bars:
        return None
    vol_sum = 0
    pv_sum = 0.0
    for bar in bars:
        vol = bar.tick_volume or 1
        typical = (bar.high + bar.low + bar.close) / 3.0
        vol_sum += vol
        pv_sum += typical * vol
    if vol_sum <= 0:
        return None
    return pv_sum / vol_sum


def session_volume_profile(bars: list[Bar], row_size: int = 50) -> VolumeProfile | None:
    """Developing session FRVP from M1 bars since NY open."""
    return compute_frvp(bars, row_size=row_size, va_pct=70.0)


def wick_volume_ratio(bar: Bar) -> tuple[float, float, float]:
    """
    Approximate volume distribution: upper_wick_share, body_share, lower_wick_share.
    Uses tick_volume as proxy when L2 orderflow unavailable.
    """
    vol = bar.tick_volume or 1
    total_range = bar.total_range
    if total_range <= 0:
        third = vol / 3.0
        return third, third, third
    upper = bar.upper_wick / total_range * vol
    lower = bar.lower_wick / total_range * vol
    body = bar.body_size / total_range * vol
    return upper, body, lower
