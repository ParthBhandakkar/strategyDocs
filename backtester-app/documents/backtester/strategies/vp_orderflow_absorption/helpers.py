"""VP + orderflow absorption strategy helpers."""

from __future__ import annotations

from datetime import time

from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time, is_after_ny_open, ny_session_date
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


def session_bars_for_vp(m1_history: list[Bar], current_time) -> list[Bar]:
    """M1 bars from NY open on the current session day."""
    if not is_after_ny_open(current_time):
        return []
    session_day = ny_session_date(current_time)
    return [
        b
        for b in m1_history
        if ny_session_date(b.time) == session_day
        and get_ny_time(b.time).time() >= time(9, 30)
    ]


def developing_session_vp(m1_history: list[Bar], current_time) -> VolumeProfile | None:
    bars = session_bars_for_vp(m1_history, current_time)
    if len(bars) < 20:
        return None
    return compute_frvp(bars)


def near_level(price: float, level: float, tolerance_pct: float) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def vwap_proxy(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    num = 0.0
    den = 0.0
    for bar in bars:
        vol = bar.tick_volume or 1
        typical = (bar.high + bar.low + bar.close) / 3.0
        num += typical * vol
        den += vol
    return num / den if den else bars[-1].close
