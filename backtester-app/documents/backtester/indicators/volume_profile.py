"""
Fixed Range and developing session Volume Profile using tick_volume.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class VolumeProfile:
    poc: float
    vah: float
    val: float
    vwap: float
    total_volume: int = 0


def compute_frvp(
    bars: list[Bar], row_size: int = 100, va_pct: float = 70.0
) -> VolumeProfile | None:
    """Compute Fixed Range Volume Profile from a list of bars."""
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

    volume_at_price: dict[float, float] = {}
    for i in range(row_size):
        level = round(overall_low + step * i, 5)
        volume_at_price[level] = 0.0

    total_vol = 0
    vwap_num = 0.0
    vwap_den = 0.0
    for bar in bars:
        vol = float(bar.tick_volume or 1)
        total_vol += int(vol)
        typical = (bar.high + bar.low + bar.close) / 3.0
        vwap_num += typical * vol
        vwap_den += vol
        bar_range = bar.high - bar.low
        if bar_range <= 0:
            continue
        for level in volume_at_price:
            if bar.low <= level <= bar.high:
                volume_at_price[level] += vol / max(1.0, bar_range / step)

    if not volume_at_price:
        return None

    poc_price = max(volume_at_price, key=volume_at_price.get)
    sorted_levels = sorted(volume_at_price.items(), key=lambda x: x[1], reverse=True)
    target_vol = sum(volume_at_price.values()) * va_pct / 100.0
    acc_vol = 0.0
    va_prices: list[float] = []
    for price, vol in sorted_levels:
        acc_vol += vol
        va_prices.append(price)
        if acc_vol >= target_vol:
            break

    vah = max(va_prices) if va_prices else overall_high
    val = min(va_prices) if va_prices else overall_low
    vwap = vwap_num / vwap_den if vwap_den > 0 else (overall_high + overall_low) / 2.0

    return VolumeProfile(
        poc=poc_price,
        vah=vah,
        val=val,
        vwap=vwap,
        total_volume=total_vol,
    )


def compute_developing_session_vp(bars: list[Bar]) -> VolumeProfile | None:
    """Developing VP for current NY session bars (from 9:30 open)."""
    return compute_frvp(bars, row_size=80, va_pct=70.0)
