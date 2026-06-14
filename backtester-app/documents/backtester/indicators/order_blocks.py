"""
Order Block Detection.
"""
from __future__ import annotations
from dataclasses import dataclass
from backtester.core import Bar

@dataclass
class OrderBlock:
    high: float
    low: float
    direction: str  # "bullish" or "bearish"
    index: int
    time: object
    mitigated: bool = False

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2

def detect_order_blocks(bars: list[Bar], lookback: int = 3) -> list[OrderBlock]:
    """Detect order blocks: last opposing candle before a displacement move."""
    obs = []
    for i in range(2, len(bars)):
        # Bullish OB: bearish candle followed by strong bullish displacement
        if bars[i-1].is_bearish and bars[i].is_bullish:
            if bars[i].close > bars[i-1].high and bars[i].body_size > bars[i-1].body_size * 1.5:
                obs.append(OrderBlock(
                    high=bars[i-1].high, low=bars[i-1].low, direction="bullish",
                    index=i-1, time=bars[i-1].time,
                ))
        # Bearish OB: bullish candle followed by strong bearish displacement
        if bars[i-1].is_bullish and bars[i].is_bearish:
            if bars[i].close < bars[i-1].low and bars[i].body_size > bars[i-1].body_size * 1.5:
                obs.append(OrderBlock(
                    high=bars[i-1].high, low=bars[i-1].low, direction="bearish",
                    index=i-1, time=bars[i-1].time,
                ))
    return obs

def update_ob_mitigation(obs: list[OrderBlock], bar: Bar):
    for ob in obs:
        if ob.mitigated:
            continue
        if ob.direction == "bullish" and bar.low <= ob.midpoint:
            ob.mitigated = True
        elif ob.direction == "bearish" and bar.high >= ob.midpoint:
            ob.mitigated = True
