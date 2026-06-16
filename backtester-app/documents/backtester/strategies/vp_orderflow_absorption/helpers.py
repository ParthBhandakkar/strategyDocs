"""Orderflow absorption helpers for VP Orderflow Absorption strategy."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str
    level: float
    cluster_high: float
    cluster_low: float
    wick_extreme: float
    reference_bar_time: str


def _level_tolerance(price: float, symbol: str) -> float:
    sym = symbol.upper()
    if "XAU" in sym:
        return max(0.5, price * 0.0002)
    if sym in {"BTCUSD", "ETHUSD"}:
        return max(5.0, price * 0.0005)
    return max(0.0002, price * 0.0001)


def price_near_level(price: float, level: float, symbol: str) -> bool:
    return abs(price - level) <= _level_tolerance(price, symbol)


def buyer_absorption(bar: Bar, vol_threshold: float) -> bool:
    """Heavy volume in upper wick with limited upward follow-through."""
    if bar.upper_wick <= 0:
        return False
    if bar.tick_volume < vol_threshold:
        return False
    body = max(bar.body_size, 1e-9)
    wick_ratio = bar.upper_wick / body
    return wick_ratio >= 1.2 and bar.close <= bar.body_high


def seller_absorption(bar: Bar, vol_threshold: float) -> bool:
    if bar.lower_wick <= 0:
        return False
    if bar.tick_volume < vol_threshold:
        return False
    body = max(bar.body_size, 1e-9)
    wick_ratio = bar.lower_wick / body
    return wick_ratio >= 1.2 and bar.close >= bar.body_low


def median_volume(bars: list[Bar], lookback: int = 20) -> float:
    if not bars:
        return 0.0
    sample = bars[-lookback:]
    volumes = sorted(b.tick_volume for b in sample if b.tick_volume > 0)
    if not volumes:
        return 0.0
    mid = len(volumes) // 2
    return float(volumes[mid])


def cluster_bounds(bars: list[Bar], lookback: int = 5) -> tuple[float, float]:
    sample = bars[-lookback:]
    if not sample:
        return 0.0, 0.0
    return min(b.low for b in sample), max(b.high for b in sample)
