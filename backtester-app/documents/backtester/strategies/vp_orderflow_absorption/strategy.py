"""VP + Orderflow Absorption — Video #1 canonical strategy."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_post_ny_open, session_bars_for_ny_date
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    buyer_absorption,
    seller_absorption,
    price_near_level,
    median_volume,
    cluster_bounds,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes after NY open when aggressive "
        "orders fail at wicks and price inverts local order clusters."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP",
            description="Build session volume profile from post-9:30 NY M1 bars.",
            timeframe="M1",
            conditions=["After 9:30 NY", "Session developing profile"],
            key_levels=["VWAP", "POC", "VAH", "VAL"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption at extremes",
            description="Identify wick-trapped volume at VAH/VWAP/POC (short) or VAL (long).",
            timeframe="M1",
            conditions=["High tick volume in wick", "No follow-through"],
        ),
        PlaybookStep(
            step_number=3,
            title="Order inversion entry",
            description="Enter on close through nearby support/resistance cluster.",
            timeframe="M1",
            conditions=["Close below cluster for shorts", "Close above cluster for longs"],
        ),
    ]

    CLUSTER_LOOKBACK = 5

    def on_start(self):
        self._last_trade_day = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        bar = bars.get(TF.M1)
        if bar is None:
            return []

        if not is_post_ny_open(current_time):
            return []

        ny_date = get_ny_time(current_time).date()
        if self._last_trade_day == ny_date:
            return []

        m1_hist = history(None, TF.M1, 500)
        session_bars = session_bars_for_ny_date(
            [b for b in m1_hist if is_post_ny_open(b.time)],
            ny_date,
        )
        if len(session_bars) < 30:
            return []

        profile = compute_frvp(session_bars)
        if profile is None:
            return []

        vol_threshold = max(median_volume(m1_hist) * 1.5, 1.0)
        prior = m1_hist[:-1]
        if len(prior) < self.CLUSTER_LOOKBACK + 1:
            return []

        ref = prior[-1]
        cluster_low, cluster_high = cluster_bounds(prior, self.CLUSTER_LOOKBACK)

        short_levels = [profile.vah, profile.poc, profile.vwap]
        for level in short_levels:
            if not price_near_level(ref.high, level, self.symbol):
                continue
            if not buyer_absorption(ref, vol_threshold):
                continue
            if bar.close >= cluster_low:
                continue
            stop = ref.high + _stop_buffer(self.symbol)
            target = profile.val
            if stop <= bar.close or bar.close <= target:
                continue
            self._last_trade_day = ny_date
            return [
                Signal(
                    strategy_id=self.id,
                    direction=Direction.SHORT,
                    entry_price=bar.close,
                    stop_loss=stop,
                    take_profit=target,
                    timestamp=current_time,
                    symbol=self.symbol,
                    metadata={"setup": "vah_absorption_short", "level": level},
                )
            ]

        if price_near_level(ref.low, profile.val, self.symbol) and seller_absorption(ref, vol_threshold):
            if bar.close > cluster_high:
                stop = ref.low - _stop_buffer(self.symbol)
                target = profile.vwap
                if stop < bar.close < target:
                    self._last_trade_day = ny_date
                    return [
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=bar.close,
                            stop_loss=stop,
                            take_profit=target,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "val_absorption_long", "level": profile.val},
                        )
                    ]

        return []


def _stop_buffer(symbol: str) -> float:
    sym = symbol.upper()
    if "XAU" in sym:
        return 0.5
    if sym in {"BTCUSD", "ETHUSD"}:
        return 2.0
    return 0.0002
