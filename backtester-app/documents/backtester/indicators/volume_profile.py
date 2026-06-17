"""
Volume profile utilities including developing session VP and VWAP.
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
    bars: list[Bar],
    row_size: int = 80,
    va_pct: float = 70.0,
) -> VolumeProfile | None:
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
    for index in range(row_size):
        level = overall_low + step * index
        volume_at_price[round(level, 5)] = 0.0

    total_vol = 0
    vwap_num = 0.0
    for bar in bars:
        vol = max(bar.tick_volume, 1)
        total_vol += vol
        typical = (bar.high + bar.low + bar.close) / 3.0
        vwap_num += typical * vol
        bar_range = bar.high - bar.low
        if bar_range <= 0:
            continue
        for level in volume_at_price:
            if bar.low <= level <= bar.high:
                volume_at_price[level] += vol / max(1, int(bar_range / step))

    poc_price = max(volume_at_price, key=volume_at_price.get)
    sorted_levels = sorted(volume_at_price.items(), key=lambda item: item[1], reverse=True)
    target_vol = total_vol * va_pct / 100.0
    acc_vol = 0.0
    va_prices: list[float] = []
    for price, vol in sorted_levels:
        acc_vol += vol
        va_prices.append(price)
        if acc_vol >= target_vol:
            break

    vah = max(va_prices) if va_prices else overall_high
    val = min(va_prices) if va_prices else overall_low
    vwap = vwap_num / total_vol if total_vol else (overall_high + overall_low) / 2.0
    return VolumeProfile(
        poc=poc_price,
        vah=vah,
        val=val,
        vwap=vwap,
        total_volume=int(total_vol),
    )
