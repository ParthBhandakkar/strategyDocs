"""Strategy-specific helpers for VP orderflow absorption."""

from __future__ import annotations

from backtester.core import Bar
from backtester.indicators.orderflow import (
    average_volume,
    detect_absorption_at_level,
    is_buyer_absorption,
    is_seller_absorption,
    nearest_resistance_cluster,
    nearest_support_cluster,
)
from backtester.indicators.sessions import get_ny_time, is_in_session, ny_session_date
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


def session_bars_since_ny_open(m1_history: list[Bar], current_time) -> list[Bar]:
    """M1 bars from today's NY cash open (9:30) through current_time."""
    session_date = ny_session_date(current_time)
    ny_now = get_ny_time(current_time)
    result: list[Bar] = []
    for bar in m1_history:
        if ny_session_date(bar.time) != session_date:
            continue
        ny_bar = get_ny_time(bar.time)
        if ny_bar.hour > 9 or (ny_bar.hour == 9 and ny_bar.minute >= 30):
            if bar.time <= current_time:
                result.append(bar)
    return result


def developing_vp(m1_history: list[Bar], current_time) -> VolumeProfile | None:
    """Developing daily volume profile from post-9:30 NY session bars."""
    session = session_bars_since_ny_open(m1_history, current_time)
    if len(session) < 30:
        return None
    return compute_frvp(session, row_size=80, va_pct=70.0)


def pending_short_absorption(
    bar: Bar,
    bars: list[Bar],
    vp: VolumeProfile,
    min_wick_ratio: float,
) -> bool:
    """Buyer absorption near VAH/POC/VWAP — bearish bias pending inversion."""
    avg_vol = average_volume(bars)
    near_vah = detect_absorption_at_level(bar, bars, vp.vah, "above")
    near_poc = detect_absorption_at_level(bar, bars, vp.poc, "above")
    near_vwap = detect_absorption_at_level(bar, bars, vp.vwap, "above")
    if near_vah or near_poc or near_vwap:
        return True
    if bar.high >= vp.vah and is_buyer_absorption(bar, avg_vol, min_wick_ratio):
        return True
    return False


def pending_long_absorption(
    bar: Bar,
    bars: list[Bar],
    vp: VolumeProfile,
    min_wick_ratio: float,
) -> bool:
    """Seller absorption below VAL — bullish bias pending inversion."""
    avg_vol = average_volume(bars)
    near_val = detect_absorption_at_level(bar, bars, vp.val, "below")
    if near_val:
        return True
    if bar.low <= vp.val and is_seller_absorption(bar, avg_vol, min_wick_ratio):
        return True
    return False


def short_inversion_trigger(bar: Bar, bars: list[Bar], lookback: int) -> tuple[bool, float]:
    """Bearish close below close-proximity support cluster."""
    support = nearest_support_cluster(bars, lookback)
    if support is None:
        return False, 0.0
    if bar.is_bearish and bar.close < support:
        return True, support
    return False, 0.0


def long_inversion_trigger(bar: Bar, bars: list[Bar], lookback: int) -> tuple[bool, float]:
    """Bullish close above absorbed sell-order cluster (resistance)."""
    resistance = nearest_resistance_cluster(bars, lookback)
    if resistance is None:
        return False, 0.0
    if bar.is_bullish and bar.close > resistance:
        return True, resistance
    return False, 0.0
