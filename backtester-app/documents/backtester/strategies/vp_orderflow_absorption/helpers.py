"""VP + orderflow absorption helpers (strategy-local)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


@dataclass
class AbsorptionBar:
    bar: Bar
    direction: str  # "buy" or "sell"
    cluster_level: float


def session_bars_for_day(bars: list[Bar], ny_day: date) -> list[Bar]:
    """M1 bars from NY 9:30 open onward for the given NY calendar day."""
    out: list[Bar] = []
    for bar in bars:
        ny = get_ny_time(bar.time)
        if ny.date() != ny_day:
            continue
        if ny.hour > 9 or (ny.hour == 9 and ny.minute >= 30):
            out.append(bar)
    return out


def developing_vp(bars: list[Bar]) -> VolumeProfile | None:
    if len(bars) < 20:
        return None
    return compute_frvp(bars, row_size=80, va_pct=70.0)


def vwap_from_bars(bars: list[Bar]) -> float:
    total_vol = 0
    weighted = 0.0
    for bar in bars:
        vol = bar.tick_volume or 1
        typical = (bar.high + bar.low + bar.close) / 3.0
        weighted += typical * vol
        total_vol += vol
    if total_vol <= 0:
        return bars[-1].close
    return weighted / total_vol


def detect_buyer_absorption(bar: Bar, avg_volume: float) -> bool:
    """Heavy upper-wick volume without bullish follow-through."""
    if bar.upper_wick <= 0 or bar.total_range <= 0:
        return False
    vol = bar.tick_volume or 0
    if vol < max(avg_volume * 1.5, 1):
        return False
    wick_ratio = bar.upper_wick / bar.total_range
    body_top = max(bar.open, bar.close)
    return wick_ratio >= 0.35 and body_top < bar.high - bar.upper_wick * 0.25


def detect_seller_absorption(bar: Bar, avg_volume: float) -> bool:
    """Heavy lower-wick volume without bearish follow-through."""
    if bar.lower_wick <= 0 or bar.total_range <= 0:
        return False
    vol = bar.tick_volume or 0
    if vol < max(avg_volume * 1.5, 1):
        return False
    wick_ratio = bar.lower_wick / bar.total_range
    body_bottom = min(bar.open, bar.close)
    return wick_ratio >= 0.35 and body_bottom > bar.low + bar.lower_wick * 0.25


def recent_swing_low(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    lows = [b.low for b in window]
    return min(lows)


def recent_swing_high(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    highs = [b.high for b in window]
    return max(highs)
