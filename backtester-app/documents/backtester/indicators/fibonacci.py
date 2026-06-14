"""
Fibonacci Retracement & Standard Deviation Extensions.
Used for ICT standard deviation projections (-1.0, -2.0, -2.5, -4.0).
"""
from __future__ import annotations

ICT_FIB_LEVELS = [0, 0.5, 1.0, -1.0, -1.5, -2.0, -2.5, -4.0]

def fib_retracement(high: float, low: float, levels: list[float] | None = None) -> dict[float, float]:
    """Calculate Fibonacci retracement levels between high and low."""
    if levels is None:
        levels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    diff = high - low
    return {level: high - diff * level for level in levels}

def fib_extension(swing_high: float, swing_low: float, levels: list[float] | None = None) -> dict[float, float]:
    """Calculate standard deviation extension levels (ICT style).
    Negative levels project beyond the swing range."""
    if levels is None:
        levels = ICT_FIB_LEVELS
    diff = swing_high - swing_low
    return {level: swing_high - diff * level for level in levels}

def get_sd_target(swing_high: float, swing_low: float, sd_level: float = -2.0, direction: str = "bullish") -> float:
    """Get the standard deviation target price for a given direction."""
    diff = abs(swing_high - swing_low)
    if direction == "bullish":
        return swing_high + diff * abs(sd_level)
    else:
        return swing_low - diff * abs(sd_level)

def price_at_fib_level(high: float, low: float, level: float) -> float:
    """Get price at a specific fib level (0=high, 1=low)."""
    return high - (high - low) * level
