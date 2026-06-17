"""
Fixed Range Volume Profile (FRVP) — approximation using tick_volume.
"""
from __future__ import annotations
from dataclasses import dataclass
from backtester.core import Bar

@dataclass
class VolumeProfile:
    poc: float  # Point of Control
    vah: float  # Value Area High
    val: float  # Value Area Low
    vwap: float = 0.0
    total_volume: int = 0

def compute_frvp(bars: list[Bar], row_size: int = 100, va_pct: float = 70.0) -> VolumeProfile | None:
    """Compute Fixed Range Volume Profile from a list of bars using tick_volume."""
    if not bars:
        return None
    overall_high = max(b.high for b in bars)
    overall_low = min(b.low for b in bars)
    price_range = overall_high - overall_low
    if price_range <= 0:
        return None
    step = price_range / row_size
    if step <= 0:
        return None
    volume_at_price = {}
    for i in range(row_size):
        level = overall_low + step * i
        volume_at_price[round(level, 5)] = 0
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
    poc_price = max(volume_at_price, key=volume_at_price.get) if volume_at_price else (overall_high + overall_low) / 2
    sorted_levels = sorted(volume_at_price.items(), key=lambda x: x[1], reverse=True)
    target_vol = total_vol * va_pct / 100
    acc_vol = 0
    va_prices = []
    for price, vol in sorted_levels:
        acc_vol += vol
        va_prices.append(price)
        if acc_vol >= target_vol:
            break
    vah = max(va_prices) if va_prices else overall_high
    val = min(va_prices) if va_prices else overall_low
    vwap_num = 0.0
    vwap_den = 0
    for bar in bars:
        vol = bar.tick_volume or 1
        typical = (bar.high + bar.low + bar.close) / 3.0
        vwap_num += typical * vol
        vwap_den += vol
    vwap = vwap_num / vwap_den if vwap_den > 0 else (overall_high + overall_low) / 2
    return VolumeProfile(poc=poc_price, vah=vah, val=val, vwap=vwap, total_volume=total_vol)
