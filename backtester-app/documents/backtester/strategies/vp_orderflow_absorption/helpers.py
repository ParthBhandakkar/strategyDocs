"""Volume Profile + orderflow absorption helpers for cluster A."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


@dataclass
class AbsorptionEvent:
    direction: str  # "buyer" or "seller"
    bar_index: int
    wick_extreme: float
    cluster_low: float
    cluster_high: float
    volume: int


def session_bars_since_ny_open(bars: list[Bar], current_time) -> list[Bar]:
    """M1 bars from today's NY session (from 09:30) up to current_time."""
    ny_now = get_ny_time(current_time)
    session_date = ny_now.date()
    out: list[Bar] = []
    for bar in bars:
        if bar.time > current_time:
            break
        ny = get_ny_time(bar.time)
        if ny.date() != session_date:
            continue
        if ny.time().hour > 9 or (ny.time().hour == 9 and ny.time().minute >= 30):
            out.append(bar)
    return out


def compute_session_vwap(bars: list[Bar]) -> float | None:
    if not bars:
        return None
    num = 0.0
    den = 0.0
    for bar in bars:
        vol = max(bar.tick_volume, 1)
        typical = (bar.high + bar.low + bar.close) / 3.0
        num += typical * vol
        den += vol
    return num / den if den > 0 else None


def developing_session_profile(bars: list[Bar], current_time) -> VolumeProfile | None:
    session = session_bars_since_ny_open(bars, current_time)
    if len(session) < 10:
        return None
    return compute_frvp(session)


def _wick_volume_share(bar: Bar) -> tuple[float, float]:
    """Approximate volume in upper/lower wick vs body using geometry."""
    total = max(bar.total_range, 1e-9)
    vol = max(bar.tick_volume, 1)
    upper_share = bar.upper_wick / total
    lower_share = bar.lower_wick / total
    body_share = max(bar.body_size / total, 0.0)
    remaining = max(1.0 - body_share, 0.01)
    upper_vol = vol * (upper_share / remaining)
    lower_vol = vol * (lower_share / remaining)
    return upper_vol, lower_vol


def detect_buyer_absorption(bar: Bar, avg_volume: float) -> bool:
    """Heavy buying in upper wick without bullish follow-through."""
    if bar.tick_volume < avg_volume * 1.2:
        return False
    upper_vol, _ = _wick_volume_share(bar)
    if upper_vol < avg_volume * 0.6:
        return False
    if bar.upper_wick < bar.body_size * 0.5:
        return False
    return bar.close <= bar.body_high


def detect_seller_absorption(bar: Bar, avg_volume: float) -> bool:
    if bar.tick_volume < avg_volume * 1.2:
        return False
    _, lower_vol = _wick_volume_share(bar)
    if lower_vol < avg_volume * 0.6:
        return False
    if bar.lower_wick < bar.body_size * 0.5:
        return False
    return bar.close >= bar.body_low


def find_order_cluster(bars: list[Bar], lookback: int = 5) -> tuple[float, float, float]:
    """Return (cluster_low, cluster_high, avg_volume) from recent bars."""
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if not window:
        return 0.0, 0.0, 0.0
    avg_vol = sum(b.tick_volume for b in window) / len(window)
    return min(b.low for b in window), max(b.high for b in window), avg_vol


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def scan_absorption_events(
    bars: list[Bar], lookback: int = 8
) -> list[AbsorptionEvent]:
    events: list[AbsorptionEvent] = []
    if len(bars) < lookback + 2:
        return events
    for i in range(len(bars) - lookback, len(bars) - 1):
        window = bars[max(0, i - lookback) : i + 1]
        cluster_low, cluster_high, avg_vol = find_order_cluster(window[:-1], lookback=min(5, len(window) - 1))
        bar = window[-1]
        if detect_buyer_absorption(bar, avg_vol):
            events.append(
                AbsorptionEvent(
                    direction="buyer",
                    bar_index=i,
                    wick_extreme=bar.high,
                    cluster_low=cluster_low,
                    cluster_high=cluster_high,
                    volume=bar.tick_volume,
                )
            )
        elif detect_seller_absorption(bar, avg_vol):
            events.append(
                AbsorptionEvent(
                    direction="seller",
                    bar_index=i,
                    wick_extreme=bar.low,
                    cluster_low=cluster_low,
                    cluster_high=cluster_high,
                    volume=bar.tick_volume,
                )
            )
    return events
