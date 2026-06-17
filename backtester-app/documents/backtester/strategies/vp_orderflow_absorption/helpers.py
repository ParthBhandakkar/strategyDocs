"""
Session developing VP and absorption helpers for vp_orderflow_absorption.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar
from backtester.indicators.orderflow import compute_vwap, is_buyer_absorption, is_seller_absorption
from backtester.indicators.sessions import get_ny_time, is_post_ny_open, session_date_ny
from backtester.indicators.structure import detect_swing_highs, detect_swing_lows
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


def session_bars_since_open(m1_history: list[Bar], current_time: datetime) -> list[Bar]:
    """M1 bars from today's NY 9:30 open through current_time (inclusive)."""
    if not is_post_ny_open(current_time):
        return []
    today = session_date_ny(current_time)
    session: list[Bar] = []
    for bar in m1_history:
        ny = get_ny_time(bar.time)
        if ny.date() != today:
            continue
        if ny.time().hour < 9 or (ny.time().hour == 9 and ny.time().minute < 30):
            continue
        if bar.time <= current_time:
            session.append(bar)
    return session


def developing_session_vp(m1_history: list[Bar], current_time: datetime) -> VolumeProfile | None:
    session = session_bars_since_open(m1_history, current_time)
    if len(session) < 20:
        return None
    return compute_frvp(session, row_size=80, va_pct=70.0)


def session_vwap(m1_history: list[Bar], current_time: datetime) -> float | None:
    session = session_bars_since_open(m1_history, current_time)
    return compute_vwap(session)


def near_level(price: float, level: float, tolerance_pct: float = 0.0008) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def recent_support_cluster(m1_history: list[Bar], lookback: int = 12) -> float | None:
    swings = detect_swing_lows(m1_history[-lookback:], lookback=2)
    if not swings:
        lows = [b.low for b in m1_history[-lookback:]]
        return min(lows) if lows else None
    return swings[-1].price


def recent_resistance_cluster(m1_history: list[Bar], lookback: int = 12) -> float | None:
    swings = detect_swing_highs(m1_history[-lookback:], lookback=2)
    if not swings:
        highs = [b.high for b in m1_history[-lookback:]]
        return max(highs) if highs else None
    return swings[-1].price
