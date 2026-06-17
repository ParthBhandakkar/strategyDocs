"""VP + orderflow absorption helpers."""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


def developing_session_bars(bars: list[Bar], current_time: datetime) -> list[Bar]:
    day = get_ny_time(current_time).date()
    return [bar for bar in bars if get_ny_time(bar.time).date() == day and bar.time <= current_time]


def compute_developing_vp(bars: list[Bar], current_time: datetime) -> VolumeProfile | None:
    session_bars = developing_session_bars(bars, current_time)
    if len(session_bars) < 20:
        return None
    return compute_frvp(session_bars)


def compute_vwap(bars: list[Bar]) -> float | None:
    if not bars:
        return None
    total_volume = 0
    weighted = 0.0
    for bar in bars:
        vol = max(bar.tick_volume, 1)
        typical = (bar.high + bar.low + bar.close) / 3.0
        weighted += typical * vol
        total_volume += vol
    if total_volume <= 0:
        return None
    return weighted / total_volume
