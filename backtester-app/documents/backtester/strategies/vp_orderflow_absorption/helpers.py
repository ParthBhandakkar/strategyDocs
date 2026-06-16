"""
Volume-profile orderflow absorption helpers for VP + orderflow strategies.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


@dataclass
class AbsorptionSignal:
    direction: str
    cluster_high: float
    cluster_low: float
    absorption_high: float
    absorption_low: float
    vp_level: str


def compute_session_vwap(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    total_volume = 0
    weighted = 0.0
    for bar in bars:
        vol = bar.tick_volume or 1
        typical = (bar.high + bar.low + bar.close) / 3.0
        weighted += typical * vol
        total_volume += vol
    return weighted / total_volume if total_volume > 0 else bars[-1].close


def detect_wick_absorption(
    bar: Bar,
    side: str,
    min_wick_ratio: float = 0.35,
    min_volume: int = 50,
) -> bool:
    """Proxy orderflow absorption using tick volume concentrated in wicks."""
    if bar.total_range <= 0:
        return False
    volume = bar.tick_volume or 0
    if volume < min_volume:
        return False
    if side == "buyers":
        wick = bar.upper_wick
        return wick / bar.total_range >= min_wick_ratio and bar.close <= bar.body_high
    wick = bar.lower_wick
    return wick / bar.total_range >= min_wick_ratio and bar.close >= bar.body_low


def find_order_cluster_level(bars: list[Bar], lookback: int = 5) -> tuple[float, float]:
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    if not recent:
        return 0.0, 0.0
    return min(b.low for b in recent), max(b.high for b in recent)


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def build_developing_vp(bars: list[Bar]) -> VolumeProfile | None:
    if len(bars) < 20:
        return None
    return compute_frvp(bars, row_size=80, va_pct=70.0)
