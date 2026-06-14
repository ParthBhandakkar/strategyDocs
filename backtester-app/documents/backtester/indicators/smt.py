"""
SMT Divergence — Smart Money Technique divergence between correlated instruments.
"""
from __future__ import annotations
from dataclasses import dataclass
from backtester.core import Bar
from backtester.indicators.structure import detect_swing_highs, detect_swing_lows

@dataclass
class SMTDivergence:
    index: int
    time: object
    direction: str  # "bullish" or "bearish"
    primary_price: float
    secondary_price: float

def detect_smt_divergence(bars_a: list[Bar], bars_b: list[Bar], lookback: int = 20) -> list[SMTDivergence]:
    """Detect SMT divergence between two correlated instruments."""
    divergences = []
    if len(bars_a) < lookback or len(bars_b) < lookback:
        return divergences
    a_recent = bars_a[-lookback:]
    b_recent = bars_b[-lookback:]
    a_highs = detect_swing_highs(a_recent, lookback=2)
    a_lows = detect_swing_lows(a_recent, lookback=2)
    b_highs = detect_swing_highs(b_recent, lookback=2)
    b_lows = detect_swing_lows(b_recent, lookback=2)
    # Bullish SMT: A makes lower low but B makes higher low
    if len(a_lows) >= 2 and len(b_lows) >= 2:
        if a_lows[-1].price < a_lows[-2].price and b_lows[-1].price > b_lows[-2].price:
            divergences.append(SMTDivergence(
                index=a_lows[-1].index, time=a_lows[-1].time, direction="bullish",
                primary_price=a_lows[-1].price, secondary_price=b_lows[-1].price,
            ))
    # Bearish SMT: A makes higher high but B makes lower high
    if len(a_highs) >= 2 and len(b_highs) >= 2:
        if a_highs[-1].price > a_highs[-2].price and b_highs[-1].price < b_highs[-2].price:
            divergences.append(SMTDivergence(
                index=a_highs[-1].index, time=a_highs[-1].time, direction="bearish",
                primary_price=a_highs[-1].price, secondary_price=b_highs[-1].price,
            ))
    return divergences
