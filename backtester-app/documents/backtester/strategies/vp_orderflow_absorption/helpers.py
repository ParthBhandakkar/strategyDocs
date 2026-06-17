"""VP orderflow absorption helpers."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


@dataclass
class AbsorptionEvent:
    direction: str
    bar_index: int
    level: float
    wick_extreme: float


def session_bars_since_ny_open(bars: list[Bar], current_index: int) -> list[Bar]:
    """Return developing session bars up to and including current_index."""
    if current_index < 0 or current_index >= len(bars):
        return []
    current_day = bars[current_index].time.date()
    session: list[Bar] = []
    for i in range(current_index + 1):
        bar = bars[i]
        if bar.time.date() != current_day:
            continue
        session.append(bar)
    return session


def compute_developing_vp(bars: list[Bar]) -> VolumeProfile | None:
    if len(bars) < 10:
        return None
    return compute_frvp(bars, row_size=50, va_pct=70.0)


def vwap_from_bars(bars: list[Bar]) -> float | None:
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


def detect_wick_absorption(bar: Bar, direction: str, min_wick_ratio: float = 1.5) -> bool:
    """Proxy for L2 absorption using wick volume concentration."""
    body = max(bar.body_size, 1e-9)
    vol = max(bar.tick_volume, 0)
    if vol < 50:
        return False
    if direction == "bearish":
        return bar.upper_wick / body >= min_wick_ratio and bar.upper_wick > bar.lower_wick
    return bar.lower_wick / body >= min_wick_ratio and bar.lower_wick > bar.upper_wick


def recent_swing_low(bars: list[Bar], lookback: int = 8) -> float | None:
    window = bars[-lookback:]
    if len(window) < 3:
        return None
    return min(b.low for b in window[:-1])


def recent_swing_high(bars: list[Bar], lookback: int = 8) -> float | None:
    window = bars[-lookback:]
    if len(window) < 3:
        return None
    return max(b.high for b in window[:-1])
