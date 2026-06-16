"""VP Orderflow Absorption — strategy-specific helpers."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


@dataclass
class AbsorptionSignal:
    direction: str  # "short" or "long"
    absorption_high: float
    absorption_low: float
    cluster_level: float
    vp: VolumeProfile


def session_bars_since_ny_open(bars: list[Bar], current_time) -> list[Bar]:
    """Bars from today's NY regular session (9:30+) up to current_time."""
    ny_date = get_ny_time(current_time).date()
    result: list[Bar] = []
    for bar in bars:
        if bar.time > current_time:
            break
        ny = get_ny_time(bar.time)
        if ny.date() != ny_date:
            continue
        if is_in_session(bar.time, "new_york") or (
            ny.time().hour == 9 and ny.time().minute >= 30
        ):
            result.append(bar)
    return result


def wick_volume_ratio(bar: Bar, side: str) -> float:
    """Proxy for orderflow absorption: tick volume concentrated in wick vs body."""
    vol = bar.tick_volume or 1
    body = max(bar.body_size, 1e-9)
    if side == "upper":
        wick = bar.upper_wick
    else:
        wick = bar.lower_wick
    if wick <= 0:
        return 0.0
    return (vol * (wick / max(bar.total_range, 1e-9))) / body


def detect_buyer_absorption(bar: Bar, min_ratio: float = 1.5) -> bool:
    """Heavy buying at highs failed to push price higher (upper wick absorption)."""
    if bar.upper_wick <= 0:
        return False
    ratio = wick_volume_ratio(bar, "upper")
    stalled = bar.close <= bar.open + bar.body_size * 0.3
    return ratio >= min_ratio and stalled and bar.upper_wick > bar.body_size


def detect_seller_absorption(bar: Bar, min_ratio: float = 1.5) -> bool:
    """Heavy selling at lows failed to push price lower (lower wick absorption)."""
    if bar.lower_wick <= 0:
        return False
    ratio = wick_volume_ratio(bar, "lower")
    stalled = bar.close >= bar.open - bar.body_size * 0.3
    return ratio >= min_ratio and stalled and bar.lower_wick > bar.body_size


def local_support_cluster(bars: list[Bar], lookback: int = 20) -> float:
    if len(bars) < 2:
        return bars[-1].low if bars else 0.0
    window = bars[-lookback:]
    return min(b.low for b in window)


def local_resistance_cluster(bars: list[Bar], lookback: int = 20) -> float:
    if len(bars) < 2:
        return bars[-1].high if bars else 0.0
    window = bars[-lookback:]
    return max(b.high for b in window)


def developing_session_vp(bars: list[Bar], current_time) -> VolumeProfile | None:
    session = session_bars_since_ny_open(bars, current_time)
    if len(session) < 30:
        return None
    return compute_frvp(session, row_size=50, va_pct=70.0)
