"""
Fair Value Gap (FVG) Detection — regular FVGs and Inversion FVGs (IFVG).
Core ICT concept used in nearly every strategy.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from backtester.core import Bar


@dataclass
class FVG:
    """A Fair Value Gap zone."""
    high: float       # Upper boundary of the gap
    low: float        # Lower boundary of the gap
    direction: str    # "bullish" or "bearish"
    start_index: int  # Bar index where FVG formed
    start_time: object  # datetime
    mitigated: bool = False
    inverted: bool = False  # True if this became an IFVG
    midpoint: float = 0.0

    def __post_init__(self):
        self.midpoint = (self.high + self.low) / 2

    @property
    def size(self) -> float:
        return self.high - self.low

    def contains_price(self, price: float) -> bool:
        """Check if a price is within this FVG zone."""
        return self.low <= price <= self.high


def detect_fvg(bars: list[Bar], min_gap_pips: float = 0) -> list[FVG]:
    """
    Detect Fair Value Gaps in a bar series.
    
    A bullish FVG: bar[i-2].high < bar[i].low (gap between bar 1's high and bar 3's low)
    A bearish FVG: bar[i-2].low > bar[i].high (gap between bar 1's low and bar 3's high)
    
    The middle candle (bar[i-1]) is the displacement candle.
    """
    fvgs = []
    for i in range(2, len(bars)):
        # Bullish FVG: Gap up
        if bars[i].low > bars[i - 2].high:
            gap_size = bars[i].low - bars[i - 2].high
            if gap_size > min_gap_pips:
                fvgs.append(FVG(
                    high=bars[i].low,
                    low=bars[i - 2].high,
                    direction="bullish",
                    start_index=i - 1,
                    start_time=bars[i - 1].time,
                ))

        # Bearish FVG: Gap down
        if bars[i].high < bars[i - 2].low:
            gap_size = bars[i - 2].low - bars[i].high
            if gap_size > min_gap_pips:
                fvgs.append(FVG(
                    high=bars[i - 2].low,
                    low=bars[i].high,
                    direction="bearish",
                    start_index=i - 1,
                    start_time=bars[i - 1].time,
                ))

    return fvgs


def detect_ifvg(bars: list[Bar], existing_fvgs: list[FVG] | None = None) -> list[FVG]:
    """
    Detect Inversion Fair Value Gaps (IFVG).
    An IFVG occurs when price closes through an existing FVG,
    inverting its polarity (bullish FVG becomes bearish resistance, vice versa).
    """
    if existing_fvgs is None:
        existing_fvgs = detect_fvg(bars)

    ifvgs = []
    for fvg in existing_fvgs:
        if fvg.mitigated or fvg.inverted:
            continue

        # Check bars after the FVG formed
        for i in range(fvg.start_index + 2, len(bars)):
            bar = bars[i]

            if fvg.direction == "bullish":
                # Bullish FVG inverts when price closes below its low
                if bar.close < fvg.low:
                    inverted_fvg = FVG(
                        high=fvg.high,
                        low=fvg.low,
                        direction="bearish",  # Inverted polarity
                        start_index=i,
                        start_time=bar.time,
                        inverted=True,
                    )
                    fvg.inverted = True
                    ifvgs.append(inverted_fvg)
                    break

            elif fvg.direction == "bearish":
                # Bearish FVG inverts when price closes above its high
                if bar.close > fvg.high:
                    inverted_fvg = FVG(
                        high=fvg.high,
                        low=fvg.low,
                        direction="bullish",  # Inverted polarity
                        start_index=i,
                        start_time=bar.time,
                        inverted=True,
                    )
                    fvg.inverted = True
                    ifvgs.append(inverted_fvg)
                    break

    return ifvgs


def update_fvg_mitigation(fvgs: list[FVG], current_bar: Bar) -> list[FVG]:
    """
    Check which FVGs have been mitigated by the current bar.
    A bullish FVG is mitigated when price trades down to its midpoint or lower boundary.
    A bearish FVG is mitigated when price trades up to its midpoint or upper boundary.
    """
    for fvg in fvgs:
        if fvg.mitigated:
            continue
        if fvg.direction == "bullish" and current_bar.low <= fvg.midpoint:
            fvg.mitigated = True
        elif fvg.direction == "bearish" and current_bar.high >= fvg.midpoint:
            fvg.mitigated = True
    return fvgs


def get_unmitigated_fvgs(fvgs: list[FVG], direction: str | None = None) -> list[FVG]:
    """Get all FVGs that haven't been mitigated yet."""
    result = [f for f in fvgs if not f.mitigated]
    if direction:
        result = [f for f in result if f.direction == direction]
    return result


def find_nearest_fvg(
    fvgs: list[FVG],
    price: float,
    direction: str,
    above: bool = True,
) -> Optional[FVG]:
    """Find the nearest unmitigated FVG above or below a price."""
    candidates = get_unmitigated_fvgs(fvgs, direction)
    if above:
        candidates = [f for f in candidates if f.low > price]
        candidates.sort(key=lambda f: f.low)
    else:
        candidates = [f for f in candidates if f.high < price]
        candidates.sort(key=lambda f: f.high, reverse=True)
    return candidates[0] if candidates else None
