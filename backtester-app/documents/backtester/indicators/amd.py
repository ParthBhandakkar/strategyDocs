"""
Power of Three (AMD) — Accumulation, Manipulation, Distribution detection.
"""
from __future__ import annotations
from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time

def detect_candle_open_price(bars: list[Bar], target_hour: int, target_minute: int = 0) -> float | None:
    """Get the opening price of a candle at a specific NY time."""
    for bar in reversed(bars):
        bt = get_ny_time(bar.time)
        if bt.hour == target_hour and bt.minute == target_minute:
            return bar.open
    return None

def detect_po3_phase(bars: list[Bar], open_price: float, current_bar: Bar) -> str:
    """Determine current Power of Three phase relative to the session open price."""
    if len(bars) < 5:
        return "accumulation"
    price = current_bar.close
    recent_high = max(b.high for b in bars[-10:])
    recent_low = min(b.low for b in bars[-10:])
    range_size = recent_high - recent_low
    if range_size == 0:
        return "accumulation"
    distance_from_open = abs(price - open_price)
    if distance_from_open < range_size * 0.3:
        return "accumulation"
    elif distance_from_open < range_size * 0.6:
        return "manipulation"
    else:
        return "distribution"

def is_price_above_open(price: float, open_price: float) -> bool:
    return price > open_price

def is_price_below_open(price: float, open_price: float) -> bool:
    return price < open_price
