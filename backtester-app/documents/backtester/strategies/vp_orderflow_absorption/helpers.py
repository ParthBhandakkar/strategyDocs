"""Strategy-specific helpers for VP + orderflow absorption."""

from __future__ import annotations

from dataclasses import dataclass

from backtester.core import Bar
from backtester.indicators.sessions import get_ny_time, is_post_ny_open
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp


@dataclass
class AbsorptionSignal:
    direction: str
    absorption_high: float
    absorption_low: float
    cluster_level: float
    vp: VolumeProfile
    vwap: float


def session_bars_for_day(bars: list[Bar], current_time) -> list[Bar]:
    """M1 bars from NY session start (9:30) on the current NY date."""
    ny_date = get_ny_time(current_time).date()
    out: list[Bar] = []
    for bar in bars:
        ny = get_ny_time(bar.time)
        if ny.date() != ny_date:
            continue
        if is_post_ny_open(bar.time):
            out.append(bar)
    return out


def compute_session_vwap(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    num = 0.0
    den = 0
    for bar in bars:
        vol = bar.tick_volume or 1
        typical = (bar.high + bar.low + bar.close) / 3.0
        num += typical * vol
        den += vol
    return num / den if den else bars[-1].close


def wick_volume_proxy(bar: Bar) -> tuple[float, float, float]:
    """Proxy orderflow: allocate tick_volume to upper wick, body, lower wick."""
    vol = float(bar.tick_volume or 1)
    total_range = bar.total_range
    if total_range <= 0:
        third = vol / 3.0
        return third, third, third
    upper = bar.upper_wick / total_range * vol
    lower = bar.lower_wick / total_range * vol
    body = bar.body_size / total_range * vol
    return upper, body, lower


def is_buyer_absorption(bar: Bar, min_wick_ratio: float = 1.5) -> bool:
    """Heavy aggressive buying in upper wick without bullish follow-through."""
    if not bar.is_bullish and bar.upper_wick <= bar.lower_wick:
        return False
    upper, body, _ = wick_volume_proxy(bar)
    if body <= 0:
        return upper > 0
    return upper / body >= min_wick_ratio and bar.upper_wick > bar.body_size * 0.5


def is_seller_absorption(bar: Bar, min_wick_ratio: float = 1.5) -> bool:
    """Heavy aggressive selling in lower wick without bearish follow-through."""
    if not bar.is_bearish and bar.lower_wick <= bar.upper_wick:
        return False
    _, body, lower = wick_volume_proxy(bar)
    if body <= 0:
        return lower > 0
    return lower / body >= min_wick_ratio and bar.lower_wick > bar.body_size * 0.5


def near_level(price: float, level: float, tolerance_pct: float = 0.0015) -> bool:
    if level <= 0:
        return False
    return abs(price - level) / level <= tolerance_pct


def recent_swing_low(bars: list[Bar], lookback: int = 10) -> float:
    window = bars[-lookback:] if len(bars) >= lookback else bars
    return min(b.low for b in window) if window else 0.0


def recent_swing_high(bars: list[Bar], lookback: int = 10) -> float:
    window = bars[-lookback:] if len(bars) >= lookback else bars
    return max(b.high for b in window) if window else 0.0


def evaluate_absorption_setup(
    history: list[Bar],
    current_bar: Bar,
    min_session_bars: int = 30,
) -> AbsorptionSignal | None:
    """
    Detect VP extreme absorption + order-cluster inversion on bar close.
    Uses only bars available at current_time (no future data).
    """
    if not is_post_ny_open(current_bar.time):
        return None

    session_bars = session_bars_for_day(history, current_bar.time)
    if len(session_bars) < min_session_bars:
        return None

    vp = compute_frvp(session_bars)
    if vp is None:
        return None

    vwap = compute_session_vwap(session_bars)
    prior = session_bars[:-1] if session_bars else []
    if len(prior) < 5:
        return None

    check_bar = prior[-1]
    cluster_lookback = 10
    swing_low = recent_swing_low(prior, cluster_lookback)
    swing_high = recent_swing_high(prior, cluster_lookback)

    # Short: buyer absorption at VAH/POC/VWAP, then close below support cluster
    at_upper_extreme = (
        near_level(check_bar.high, vp.vah)
        or near_level(check_bar.high, vp.poc)
        or near_level(check_bar.high, vwap)
    )
    if at_upper_extreme and is_buyer_absorption(check_bar):
        if current_bar.close < swing_low and current_bar.is_bearish:
            stop = check_bar.high
            target = vp.val
            if stop > current_bar.close and target < current_bar.close:
                return AbsorptionSignal(
                    direction="SHORT",
                    absorption_high=check_bar.high,
                    absorption_low=check_bar.low,
                    cluster_level=swing_low,
                    vp=vp,
                    vwap=vwap,
                )

    # Long: seller absorption below VAL, then close back above sell cluster
    below_val = check_bar.close < vp.val or near_level(check_bar.low, vp.val)
    if below_val and is_seller_absorption(check_bar):
        if current_bar.close > swing_high and current_bar.is_bullish:
            stop = check_bar.low
            target = vwap
            if stop < current_bar.close and target > current_bar.close:
                return AbsorptionSignal(
                    direction="LONG",
                    absorption_high=check_bar.high,
                    absorption_low=check_bar.low,
                    cluster_level=swing_high,
                    vp=vp,
                    vwap=vwap,
                )

    return None
