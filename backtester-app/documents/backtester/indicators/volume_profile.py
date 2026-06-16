"""
Fixed Range Volume Profile (FRVP) — approximation using tick_volume.
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
    row_size: int = 100,
    va_pct: float = 70.0,
) -> VolumeProfile | None:
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
    sorted_levels = sorted(volume_at_price.items(), key=lambda x: x[1], reverse=True)
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
    vwap = compute_vwap(bars)
    return VolumeProfile(
        poc=poc_price,
        vah=vah,
        val=val,
        vwap=vwap,
        total_volume=total_vol,
    )


def compute_vwap(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    cumulative_pv = 0.0
    cumulative_vol = 0
    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / 3.0
        vol = bar.tick_volume or 1
        cumulative_pv += typical * vol
        cumulative_vol += vol
    if cumulative_vol <= 0:
        return bars[-1].close
    return cumulative_pv / cumulative_vol


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """Return upper-wick and lower-wick volume concentration proxies."""
    total = bar.tick_volume or 1
    total_range = max(bar.total_range, 1e-9)
    upper_share = bar.upper_wick / total_range
    lower_share = bar.lower_wick / total_range
    return upper_share * total, lower_share * total
