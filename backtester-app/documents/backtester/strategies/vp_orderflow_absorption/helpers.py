"""Strategy-specific helpers for developing session volume profile."""

from __future__ import annotations

from backtester.core import Bar
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


def compute_vwap(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    total_volume = 0
    weighted = 0.0
    for bar in bars:
        vol = bar.tick_volume or 1
        typical = (bar.high + bar.low + bar.close) / 3.0
        weighted += typical * vol
        total_volume += vol
    return weighted / total_volume if total_volume > 0 else bars[-1].close


def developing_session_profile(bars: list[Bar]) -> VolumeProfile | None:
    """Developing NY session VP with VWAP used as POC reference."""
    profile = compute_frvp(bars)
    if profile is None:
        return None
    profile.poc = compute_vwap(bars)
    return profile
