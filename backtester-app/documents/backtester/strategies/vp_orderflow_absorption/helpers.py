"""Strategy-only helpers for VP orderflow absorption."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time


@dataclass
class AbsorptionEvent:
    direction: str
    wick_high: float
    wick_low: float
    cluster_level: float
    bar_time: object


def session_bars_since_ny_open(bars: list[Bar], current_time) -> list[Bar]:
    """Return M1 bars from the current NY session date at/after 09:30 NY."""
    current_ny = get_ny_time(current_time)
    session_date = current_ny.date()
    result: list[Bar] = []
    for bar in bars:
        bar_ny = get_ny_time(bar.time)
        if bar_ny.date() != session_date:
            continue
        if bar_ny.hour > 9 or (bar_ny.hour == 9 and bar_ny.minute >= 30):
            result.append(bar)
    return result


def is_post_ny_open(current_time) -> bool:
    ny = get_ny_time(current_time)
    return ny.hour > 9 or (ny.hour == 9 and ny.minute >= 30)


def detect_buyer_absorption(bar: Bar, volume_threshold: int = 50) -> bool:
    """Heavy tick volume in upper wick with weak bullish follow-through."""
    if bar.total_range <= 0:
        return False
    volume = bar.tick_volume or 0
    if volume < volume_threshold:
        return False
    upper_wick_ratio = bar.upper_wick / bar.total_range
    body_ratio = bar.body_size / bar.total_range
    return upper_wick_ratio >= 0.35 and body_ratio <= 0.45


def detect_seller_absorption(bar: Bar, volume_threshold: int = 50) -> bool:
    """Heavy tick volume in lower wick with weak bearish follow-through."""
    if bar.total_range <= 0:
        return False
    volume = bar.tick_volume or 0
    if volume < volume_threshold:
        return False
    lower_wick_ratio = bar.lower_wick / bar.total_range
    body_ratio = bar.body_size / bar.total_range
    return lower_wick_ratio >= 0.35 and body_ratio <= 0.45


def recent_support_cluster(bars: list[Bar], lookback: int = 8) -> float:
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if not window:
        return 0.0
    return min(bar.low for bar in window)


def recent_resistance_cluster(bars: list[Bar], lookback: int = 8) -> float:
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if not window:
        return 0.0
    return max(bar.high for bar in window)
