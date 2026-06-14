"""
Market Structure Detection — swing highs/lows, MSS, BOS, CHOCH.
Foundation for all ICT/SMC strategies.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from backtester.core import Bar


@dataclass
class SwingPoint:
    """A detected swing high or low."""
    index: int
    price: float
    time: object  # datetime
    is_high: bool  # True = swing high, False = swing low
    swept: bool = False


@dataclass
class StructureShift:
    """A market structure shift (MSS/BOS/CHOCH)."""
    index: int
    price: float
    time: object
    direction: str  # "bullish" or "bearish"
    shift_type: str  # "MSS", "BOS", "CHOCH"
    broken_level: float = 0.0


def detect_swing_highs(bars: list[Bar], lookback: int = 3) -> list[SwingPoint]:
    """
    Detect swing highs: a bar whose high is higher than the highs
    of 'lookback' bars on either side.
    """
    swings = []
    for i in range(lookback, len(bars) - lookback):
        is_swing = True
        for j in range(1, lookback + 1):
            if bars[i].high <= bars[i - j].high or bars[i].high <= bars[i + j].high:
                is_swing = False
                break
        if is_swing:
            swings.append(SwingPoint(
                index=i, price=bars[i].high, time=bars[i].time, is_high=True
            ))
    return swings


def detect_swing_lows(bars: list[Bar], lookback: int = 3) -> list[SwingPoint]:
    """
    Detect swing lows: a bar whose low is lower than the lows
    of 'lookback' bars on either side.
    """
    swings = []
    for i in range(lookback, len(bars) - lookback):
        is_swing = True
        for j in range(1, lookback + 1):
            if bars[i].low >= bars[i - j].low or bars[i].low >= bars[i + j].low:
                is_swing = False
                break
        if is_swing:
            swings.append(SwingPoint(
                index=i, price=bars[i].low, time=bars[i].time, is_high=False
            ))
    return swings


def detect_all_swings(bars: list[Bar], lookback: int = 3) -> list[SwingPoint]:
    """Detect both swing highs and lows, sorted by index."""
    highs = detect_swing_highs(bars, lookback)
    lows = detect_swing_lows(bars, lookback)
    all_swings = highs + lows
    all_swings.sort(key=lambda s: s.index)
    return all_swings


def detect_mss(
    bars: list[Bar],
    swings: list[SwingPoint] | None = None,
    lookback: int = 3,
) -> list[StructureShift]:
    """
    Detect Market Structure Shifts (MSS).
    A bullish MSS: price breaks above a recent swing high after making a lower low.
    A bearish MSS: price breaks below a recent swing low after making a higher high.
    """
    if swings is None:
        swings = detect_all_swings(bars, lookback)

    shifts = []
    for i in range(1, len(swings)):
        prev = swings[i - 1]
        curr = swings[i]

        # Look for breaks in subsequent bars
        if prev.is_high and not curr.is_high:
            # We have a high then a low — check if a subsequent bar breaks above the high
            for j in range(curr.index + 1, min(curr.index + 20, len(bars))):
                if bars[j].close > prev.price:
                    shifts.append(StructureShift(
                        index=j,
                        price=bars[j].close,
                        time=bars[j].time,
                        direction="bullish",
                        shift_type="MSS",
                        broken_level=prev.price,
                    ))
                    break

        elif not prev.is_high and prev.is_high is False and curr.is_high:
            # We have a low then a high — check if a subsequent bar breaks below the low
            for j in range(curr.index + 1, min(curr.index + 20, len(bars))):
                if bars[j].close < prev.price:
                    shifts.append(StructureShift(
                        index=j,
                        price=bars[j].close,
                        time=bars[j].time,
                        direction="bearish",
                        shift_type="MSS",
                        broken_level=prev.price,
                    ))
                    break

    return shifts


def detect_bos(bars: list[Bar], lookback: int = 3) -> list[StructureShift]:
    """
    Detect Break of Structure (BOS) — a continuation pattern.
    Bullish BOS: higher high breaks above previous swing high in an uptrend.
    Bearish BOS: lower low breaks below previous swing low in a downtrend.
    """
    swings = detect_all_swings(bars, lookback)
    shifts = []

    swing_highs = [s for s in swings if s.is_high]
    swing_lows = [s for s in swings if not s.is_high]

    # Bullish BOS: each new swing high breaks above previous
    for i in range(1, len(swing_highs)):
        if swing_highs[i].price > swing_highs[i - 1].price:
            shifts.append(StructureShift(
                index=swing_highs[i].index,
                price=swing_highs[i].price,
                time=swing_highs[i].time,
                direction="bullish",
                shift_type="BOS",
                broken_level=swing_highs[i - 1].price,
            ))

    # Bearish BOS: each new swing low breaks below previous
    for i in range(1, len(swing_lows)):
        if swing_lows[i].price < swing_lows[i - 1].price:
            shifts.append(StructureShift(
                index=swing_lows[i].index,
                price=swing_lows[i].price,
                time=swing_lows[i].time,
                direction="bearish",
                shift_type="BOS",
                broken_level=swing_lows[i - 1].price,
            ))

    shifts.sort(key=lambda s: s.index)
    return shifts


def get_recent_swing_high(bars: list[Bar], lookback: int = 3, count: int = 1) -> list[SwingPoint]:
    """Get the most recent N swing highs from the bar history."""
    swings = detect_swing_highs(bars, lookback)
    return swings[-count:] if swings else []


def get_recent_swing_low(bars: list[Bar], lookback: int = 3, count: int = 1) -> list[SwingPoint]:
    """Get the most recent N swing lows from the bar history."""
    swings = detect_swing_lows(bars, lookback)
    return swings[-count:] if swings else []


def is_bullish_orderflow(bars: list[Bar], lookback: int = 20) -> bool:
    """
    Simple bullish orderflow check: recent bars making higher highs and higher lows.
    """
    if len(bars) < lookback:
        return False
    recent = bars[-lookback:]
    highs = [b.high for b in recent]
    lows = [b.low for b in recent]
    # Check if the trend of highs and lows is upward
    mid = len(highs) // 2
    return (max(highs[mid:]) > max(highs[:mid])) and (min(lows[mid:]) > min(lows[:mid]))


def is_bearish_orderflow(bars: list[Bar], lookback: int = 20) -> bool:
    """
    Simple bearish orderflow check: recent bars making lower highs and lower lows.
    """
    if len(bars) < lookback:
        return False
    recent = bars[-lookback:]
    highs = [b.high for b in recent]
    lows = [b.low for b in recent]
    mid = len(highs) // 2
    return (max(highs[mid:]) < max(highs[:mid])) and (min(lows[mid:]) < min(lows[:mid]))
