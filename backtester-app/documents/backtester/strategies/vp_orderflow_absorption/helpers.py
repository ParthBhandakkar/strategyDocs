"""
Developing session volume profile helpers for orderflow absorption strategy.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


@dataclass
class SessionProfile:
    profile: VolumeProfile
    vwap: float
    session_bars: list[Bar]


def session_bars_since_ny_open(all_bars: list[Bar], current_time) -> list[Bar]:
    """Return M1 bars from today's 9:30 NY open through current_time."""
    ny_now = get_ny_time(current_time)
    session_start = ny_now.replace(hour=9, minute=30, second=0, microsecond=0)
    if ny_now.time() < session_start.time() and ny_now.date() == session_start.date():
        return []
    selected: list[Bar] = []
    for bar in all_bars:
        ny_bar = get_ny_time(bar.time)
        if ny_bar.date() != ny_now.date():
            continue
        if ny_bar.time() < session_start.time():
            continue
        if bar.time > current_time:
            continue
        selected.append(bar)
    return selected


def compute_session_profile(bars: list[Bar]) -> SessionProfile | None:
    if len(bars) < 20:
        return None
    profile = compute_frvp(bars, row_size=60, va_pct=70.0)
    if profile is None:
        return None
    total_vol = sum(max(b.tick_volume, 1) for b in bars)
    if total_vol <= 0:
        vwap = bars[-1].close
    else:
        vwap = sum(b.close * max(b.tick_volume, 1) for b in bars) / total_vol
    return SessionProfile(profile=profile, vwap=vwap, session_bars=bars)


def average_volume(bars: list[Bar], lookback: int = 30) -> float:
    if not bars:
        return 0.0
    sample = bars[-lookback:]
    return sum(max(b.tick_volume, 1) for b in sample) / len(sample)


def is_buyer_absorption(bar: Bar, avg_vol: float) -> bool:
    """Heavy volume in upper wick without bullish follow-through."""
    if avg_vol <= 0:
        return False
    vol = max(bar.tick_volume, 1)
    if vol < avg_vol * 1.4:
        return False
    if bar.upper_wick <= max(bar.body_size * 0.5, bar.total_range * 0.25):
        return False
    return bar.close <= bar.body_high


def is_seller_absorption(bar: Bar, avg_vol: float) -> bool:
    """Heavy volume in lower wick without bearish follow-through."""
    if avg_vol <= 0:
        return False
    vol = max(bar.tick_volume, 1)
    if vol < avg_vol * 1.4:
        return False
    if bar.lower_wick <= max(bar.body_size * 0.5, bar.total_range * 0.25):
        return False
    return bar.close >= bar.body_low


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct
