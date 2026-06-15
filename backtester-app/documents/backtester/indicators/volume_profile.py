"""
Fixed Range Volume Profile (FRVP) — approximation using tick_volume.
"""
from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time


@dataclass
class VolumeProfile:
    poc: float
    vah: float
    val: float
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
    return VolumeProfile(poc=poc_price, vah=vah, val=val, vwap=vwap, total_volume=total_vol)


def compute_vwap(bars: list[Bar]) -> float:
    """Session VWAP from typical price * volume."""
    cum_vol = 0
    cum_pv = 0.0
    for bar in bars:
        vol = bar.tick_volume or 1
        tp = (bar.high + bar.low + bar.close) / 3.0
        cum_vol += vol
        cum_pv += tp * vol
    if cum_vol <= 0:
        return bars[-1].close if bars else 0.0
    return cum_pv / cum_vol


def get_session_bars_since_ny_open(bars: list[Bar], current_time) -> list[Bar]:
    """Bars from today's NY 9:30 open through current_time (developing daily VP)."""
    ny_now = get_ny_time(current_time)
    session_date = ny_now.date()
    result: list[Bar] = []
    for bar in bars:
        ny_t = get_ny_time(bar.time)
        if ny_t.date() != session_date:
            continue
        if ny_t.time().hour > 9 or (ny_t.time().hour == 9 and ny_t.time().minute >= 30):
            if bar.time <= current_time:
                result.append(bar)
    return result
