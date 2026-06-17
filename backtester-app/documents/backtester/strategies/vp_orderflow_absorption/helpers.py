"""
Orderflow absorption proxies using tick volume in wicks.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar


@dataclass
class AbsorptionSignal:
    direction: str
    cluster_high: float
    cluster_low: float
    absorption_bar_index: int
    volume_ratio: float


@dataclass
class OrderCluster:
    high: float
    low: float
    anchor_price: float
    volume: int


def wick_volume_ratio(bar: Bar) -> tuple[float, float]:
    total = max(bar.tick_volume, 1)
    body = max(bar.body_size, 1e-9)
    upper = bar.upper_wick
    lower = bar.lower_wick
    upper_ratio = (upper / (upper + body)) * total if upper > 0 else 0.0
    lower_ratio = (lower / (lower + body)) * total if lower > 0 else 0.0
    return upper_ratio / total, lower_ratio / total


def detect_buyer_absorption(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    if bar.total_range <= 0:
        return False
    upper_share = bar.upper_wick / bar.total_range
    body_share = bar.body_size / bar.total_range
    return upper_share >= min_wick_ratio and body_share <= 0.35 and bar.tick_volume >= 20


def detect_seller_absorption(bar: Bar, min_wick_ratio: float = 0.45) -> bool:
    if bar.total_range <= 0:
        return False
    lower_share = bar.lower_wick / bar.total_range
    body_share = bar.body_size / bar.total_range
    return lower_share >= min_wick_ratio and body_share <= 0.35 and bar.tick_volume >= 20


def find_recent_order_cluster(
    bars: list[Bar],
    lookback: int = 12,
    min_volume: int = 30,
) -> OrderCluster | None:
    if len(bars) < 3:
        return None
    peak = max(bars[-lookback:], key=lambda b: b.tick_volume, default=None)
    if peak is None or peak.tick_volume < min_volume:
        return None
    return OrderCluster(
        high=peak.high,
        low=peak.low,
        anchor_price=(peak.high + peak.low) / 2.0,
        volume=peak.tick_volume,
    )
