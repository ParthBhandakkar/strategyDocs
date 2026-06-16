"""Strategy-specific helpers for VP orderflow absorption."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time, is_after_ny_open
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


@dataclass
class AbsorptionEvent:
    direction: str  # "buyer" or "seller"
    bar: Bar
    cluster_price: float
    wick_volume_ratio: float


def session_bars_since_open(bars: list[Bar], current_bar: Bar) -> list[Bar]:
    """Return M1 bars from today's NY session after 9:30 through current bar."""
    if not is_after_ny_open(current_bar.time):
        return []
    ny_date = get_ny_time(current_bar.time).date()
    session: list[Bar] = []
    for bar in bars:
        ny = get_ny_time(bar.time)
        if ny.date() != ny_date:
            continue
        if ny.time().hour < 9 or (ny.time().hour == 9 and ny.time().minute < 30):
            continue
        if bar.time <= current_bar.time:
            session.append(bar)
    return session


def wick_volume_ratio(bar: Bar, side: str) -> float:
    total = bar.tick_volume or 1
    if total <= 0:
        return 0.0
    if side == "upper":
        wick = bar.upper_wick
    else:
        wick = bar.lower_wick
    if wick <= 0 or bar.total_range <= 0:
        return 0.0
    wick_fraction = wick / bar.total_range
    return wick_fraction * (total / max(bar.body_size / bar.total_range, 0.15))


def detect_buyer_absorption(bar: Bar, min_ratio: float = 1.2) -> bool:
    """Heavy volume in upper wick without bullish follow-through."""
    if not bar.is_bullish and bar.upper_wick <= bar.body_size:
        return False
    ratio = wick_volume_ratio(bar, "upper")
    stalled = bar.close <= bar.open + bar.upper_wick * 0.35
    return ratio >= min_ratio and stalled and bar.upper_wick > 0


def detect_seller_absorption(bar: Bar, min_ratio: float = 1.2) -> bool:
    """Heavy volume in lower wick without bearish follow-through."""
    if not bar.is_bearish and bar.lower_wick <= bar.body_size:
        return False
    ratio = wick_volume_ratio(bar, "lower")
    stalled = bar.close >= bar.open - bar.lower_wick * 0.35
    return ratio >= min_ratio and stalled and bar.lower_wick > 0


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def developing_profile(session_bars: list[Bar]) -> VolumeProfile | None:
    if len(session_bars) < 20:
        return None
    return compute_frvp(session_bars, row_size=80, va_pct=70.0)


def recent_swing_low(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < lookback + 1:
        return None
    window = bars[-lookback - 1 : -1]
    return min(b.low for b in window)


def recent_swing_high(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < lookback + 1:
        return None
    window = bars[-lookback - 1 : -1]
    return max(b.high for b in window)
