"""
Liquidity Detection — equal highs/lows, liquidity sweeps, liquidity voids.
"""
from __future__ import annotations
from dataclasses import dataclass
from backtester.core import Bar

@dataclass
class LiquidityLevel:
    price: float
    index: int
    time: object
    level_type: str  # "equal_high", "equal_low", "swing_high", "swing_low"
    swept: bool = False
    sweep_index: int = -1

def detect_equal_highs(bars: list[Bar], tolerance_pct: float = 0.0005) -> list[LiquidityLevel]:
    from backtester.indicators.structure import detect_swing_highs
    swings = detect_swing_highs(bars, lookback=3)
    levels = []
    for i in range(len(swings)):
        for j in range(i + 1, len(swings)):
            diff = abs(swings[i].price - swings[j].price)
            avg = (swings[i].price + swings[j].price) / 2
            if avg > 0 and diff / avg <= tolerance_pct:
                levels.append(LiquidityLevel(
                    price=avg, index=swings[j].index, time=swings[j].time,
                    level_type="equal_high",
                ))
                break
    return levels

def detect_equal_lows(bars: list[Bar], tolerance_pct: float = 0.0005) -> list[LiquidityLevel]:
    from backtester.indicators.structure import detect_swing_lows
    swings = detect_swing_lows(bars, lookback=3)
    levels = []
    for i in range(len(swings)):
        for j in range(i + 1, len(swings)):
            diff = abs(swings[i].price - swings[j].price)
            avg = (swings[i].price + swings[j].price) / 2
            if avg > 0 and diff / avg <= tolerance_pct:
                levels.append(LiquidityLevel(
                    price=avg, index=swings[j].index, time=swings[j].time,
                    level_type="equal_low",
                ))
                break
    return levels

def detect_liquidity_sweep(bars: list[Bar], level: float, direction: str, lookback: int = 5) -> bool:
    """Check if price swept a level (wick past + close back)."""
    if len(bars) < 2:
        return False
    recent = bars[-lookback:]
    for bar in recent:
        if direction == "high":
            if bar.high > level and bar.close < level:
                return True
        elif direction == "low":
            if bar.low < level and bar.close > level:
                return True
    return False

def check_sweep(bar: Bar, level: float, direction: str) -> bool:
    """Check if a single bar sweeps a level."""
    if direction == "high":
        return bar.high > level and bar.close < level
    elif direction == "low":
        return bar.low < level and bar.close > level
    return False
