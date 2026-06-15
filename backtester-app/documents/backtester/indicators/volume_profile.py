"""
Fixed Range Volume Profile (FRVP) — approximation using tick_volume.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.sessions import is_in_session


@dataclass
class VolumeProfile:
    poc: float
    vah: float
    val: float
    vwap: float = 0.0
    total_volume: int = 0


def compute_vwap(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    total_volume = 0
    weighted = 0.0
    for bar in bars:
        vol = max(bar.tick_volume, 1)
        typical = (bar.high + bar.low + bar.close) / 3.0
        weighted += typical * vol
        total_volume += vol
    return weighted / total_volume if total_volume else bars[-1].close


def compute_frvp(bars: list[Bar], row_size: int = 100, va_pct: float = 70.0) -> VolumeProfile | None:
    """Compute Fixed Range Volume Profile from a list of bars using tick_volume."""
    if not bars:
        return None
    overall_high = max(bar.high for bar in bars)
    overall_low = min(bar.low for bar in bars)
    price_range = overall_high - overall_low
    if price_range <= 0:
        return None
    step = price_range / row_size
    if step <= 0:
        return None
    volume_at_price: dict[float, float] = {}
    for i in range(row_size):
        level = overall_low + step * i
        volume_at_price[round(level, 5)] = 0.0
    total_vol = 0
    for bar in bars:
        vol = bar.tick_volume or 1
        total_vol += vol
        bar_range = bar.high - bar.low
        if bar_range <= 0:
            continue
        for level in volume_at_price:
            if bar.low <= level <= bar.high:
                volume_at_price[level] += vol / max(1, int(bar_range / step))
    poc_price = (
        max(volume_at_price, key=volume_at_price.get)
        if volume_at_price
        else (overall_high + overall_low) / 2
    )
    sorted_levels = sorted(volume_at_price.items(), key=lambda item: item[1], reverse=True)
    target_vol = total_vol * va_pct / 100
    acc_vol = 0.0
    va_prices: list[float] = []
    for price, vol in sorted_levels:
        acc_vol += vol
        va_prices.append(price)
        if acc_vol >= target_vol:
            break
    vah = max(va_prices) if va_prices else overall_high
    val = min(va_prices) if va_prices else overall_low
    return VolumeProfile(
        poc=poc_price,
        vah=vah,
        val=val,
        vwap=compute_vwap(bars),
        total_volume=int(total_vol),
    )


def get_developing_session_vp(bars: list[Bar], current_time) -> VolumeProfile | None:
    """Developing daily VP from NY session bars up to current_time."""
    session_bars = [
        bar
        for bar in bars
        if bar.time <= current_time and is_in_session(bar.time, "new_york")
    ]
    if len(session_bars) < 20:
        return None
    return compute_frvp(session_bars)


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct
