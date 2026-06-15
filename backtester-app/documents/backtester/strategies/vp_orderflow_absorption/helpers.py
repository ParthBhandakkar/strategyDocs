"""VP orderflow absorption helpers (strategy-local)."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str  # "buy_absorption" or "sell_absorption"
    bar_index: int
    cluster_low: float
    cluster_high: float
    wick_extreme: float


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """Approximate upper/lower wick volume share using tick_volume."""
    vol = max(bar.tick_volume, 1)
    total_range = max(bar.total_range, 1e-9)
    upper_share = bar.upper_wick / total_range
    lower_share = bar.lower_wick / total_range
    return upper_share * vol, lower_share * vol


def detect_buyer_absorption_at_high(bar: Bar, min_wick_ratio: float = 0.35) -> bool:
    """
    Bullish candle with heavy volume in upper wick and limited follow-through.
    Proxy for aggressive buyers absorbed at highs.
    """
    if bar.total_range <= 0:
        return False
    upper_vol, _ = wick_volume_ratio(bar)
    wick_ratio = bar.upper_wick / bar.total_range
    body_top = bar.body_high
    stalled = bar.close <= body_top  # close not at extreme high
    return wick_ratio >= min_wick_ratio and upper_vol > bar.tick_volume * 0.25 and stalled


def detect_seller_absorption_at_low(bar: Bar, min_wick_ratio: float = 0.35) -> bool:
    """Bearish/neutral candle with heavy lower-wick volume — sellers absorbed."""
    if bar.total_range <= 0:
        return False
    _, lower_vol = wick_volume_ratio(bar)
    wick_ratio = bar.lower_wick / bar.total_range
    stalled = bar.close >= bar.body_low
    return wick_ratio >= min_wick_ratio and lower_vol > bar.tick_volume * 0.25 and stalled


def find_local_support_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    """Recent swing low cluster for inversion trigger."""
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    lows = sorted(b.low for b in window)
    return lows[len(lows) // 3]


def find_local_resistance_cluster(bars: list[Bar], lookback: int = 8) -> float | None:
    if len(bars) < 3:
        return None
    window = bars[-lookback:]
    highs = sorted((b.high for b in window), reverse=True)
    return highs[len(highs) // 3]
