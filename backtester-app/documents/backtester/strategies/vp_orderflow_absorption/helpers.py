"""Strategy-only helpers for developing session volume profile."""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp, compute_vwap


def session_bars_since_open(bars: list[Bar], current_time: datetime, open_hour: int = 9, open_minute: int = 30) -> list[Bar]:
    """Return M1 bars from current NY session open through current_time."""
    ny_now = get_ny_time(current_time)
    session_date = ny_now.date()
    selected: list[Bar] = []
    for bar in bars:
        ny_bar = get_ny_time(bar.time)
        if ny_bar.date() != session_date:
            continue
        if ny_bar.hour > open_hour or (ny_bar.hour == open_hour and ny_bar.minute >= open_minute):
            if bar.time <= current_time:
                selected.append(bar)
    return selected


def build_session_profile(bars: list[Bar], current_time: datetime) -> tuple[VolumeProfile | None, float | None]:
    session_bars = session_bars_since_open(bars, current_time)
    if len(session_bars) < 20:
        return None, None
    profile = compute_frvp(session_bars, row_size=60, va_pct=70.0)
    vwap = compute_vwap(session_bars)
    return profile, vwap
