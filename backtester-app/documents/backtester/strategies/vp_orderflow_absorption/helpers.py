"""Volume-profile orderflow absorption helpers (strategy-local proxies)."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionEvent:
    direction: str
    cluster_price: float
    wick_extreme: float
    bar_index: int


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    """Approximate upper/lower wick volume share using tick_volume."""
    vol = max(bar.tick_volume, 1)
    total_range = max(bar.total_range, 1e-9)
    upper_share = bar.upper_wick / total_range
    lower_share = bar.lower_wick / total_range
    return upper_share * vol, lower_share * vol


def detect_buyer_absorption(bar: Bar, min_wick_share: float = 0.45) -> bool:
    """Heavy buying in upper wick without bullish follow-through body."""
    if bar.total_range <= 0:
        return False
    upper_vol, _ = wick_volume_ratio(bar)
    wick_share = bar.upper_wick / bar.total_range
    weak_body = bar.body_size / bar.total_range < 0.35
    return wick_share >= min_wick_share and upper_vol > bar.tick_volume * 0.35 and weak_body


def detect_seller_absorption(bar: Bar, min_wick_share: float = 0.45) -> bool:
    """Heavy selling in lower wick without bearish follow-through body."""
    if bar.total_range <= 0:
        return False
    _, lower_vol = wick_volume_ratio(bar)
    wick_share = bar.lower_wick / bar.total_range
    weak_body = bar.body_size / bar.total_range < 0.35
    return wick_share >= min_wick_share and lower_vol > bar.tick_volume * 0.35 and weak_body


def recent_swing_low(bars: list[Bar], lookback: int = 8) -> float | None:
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if len(window) < 3:
        return None
    lows = [b.low for b in window[:-1]]
    return min(lows) if lows else None


def recent_swing_high(bars: list[Bar], lookback: int = 8) -> float | None:
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if len(window) < 3:
        return None
    highs = [b.high for b in window[:-1]]
    return max(highs) if highs else None
