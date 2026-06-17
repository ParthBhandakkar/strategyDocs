"""Video #1 — VP + orderflow absorption at developing session extremes."""

from __future__ import annotations

from datetime import datetime

from backtester.core import Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.indicators.sessions import is_post_ny_open
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    compute_session_vwap,
    developing_session_profile,
    find_order_cluster,
    near_level,
    scan_absorption_events,
    session_bars_since_ny_open,
)


class VPOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail at wicks "
        "and price inverts local order clusters after 9:30 NY."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP",
            description="Build session VP/VWAP from 9:30 NY M1 bars only.",
            timeframe="M1",
            conditions=["Post 9:30 NY session"],
            key_levels=["POC", "VAH", "VAL", "VWAP"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption",
            description="Identify wick absorption via tick_volume concentration.",
            timeframe="M1",
            conditions=["Buyer absorption above VAH/POC/VWAP", "Seller absorption below VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Order inversion",
            description="Enter on close through nearby high-volume order cluster.",
            timeframe="M1",
            conditions=["Short below cluster after buyer absorption", "Long above cluster after seller absorption"],
        ),
    ]

    LEVEL_TOLERANCE = 0.002
    CLUSTER_LOOKBACK = 5

    def on_start(self):
        self._last_signal_day = None

    def on_bar(self, bars, history, multi_symbol_bars, current_time: datetime) -> list[Signal]:
        if not is_post_ny_open(current_time):
            return []

        m1 = bars.get(TF.M1)
        if m1 is None:
            return []

        m1_hist = history(None, TF.M1, 400)
        if len(m1_hist) < 30:
            return []

        ny_day = current_time.date()
        if self._last_signal_day == ny_day:
            return []

        session_bars = session_bars_since_ny_open(m1_hist, current_time)
        profile = developing_session_profile(m1_hist, current_time)
        if profile is None:
            return []

        vwap = compute_session_vwap(session_bars)
        if vwap is None:
            return []

        cluster_low, cluster_high, avg_vol = find_order_cluster(
            m1_hist[:-1], lookback=self.CLUSTER_LOOKBACK
        )
        if avg_vol <= 0:
            return []

        absorptions = scan_absorption_events(m1_hist)
        if not absorptions:
            return []

        last_abs = absorptions[-1]
        signals: list[Signal] = []

        if last_abs.direction == "buyer":
            at_premium = (
                near_level(m1.close, profile.vah, self.LEVEL_TOLERANCE)
                or near_level(m1.close, profile.poc, self.LEVEL_TOLERANCE)
                or near_level(m1.close, vwap, self.LEVEL_TOLERANCE)
            )
            if at_premium and m1.is_bearish and m1.close < cluster_low:
                sl = last_abs.wick_extreme
                risk = sl - m1.close
                if risk <= 0:
                    return []
                tp = m1.close - risk
                if profile.val < m1.close:
                    tp = profile.val
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=m1.close,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "buyer_absorption_inversion", "target": "VAL"},
                    )
                )
        elif last_abs.direction == "seller":
            below_val = m1.close < profile.val
            if below_val and m1.is_bullish and m1.close > cluster_high:
                sl = last_abs.wick_extreme
                risk = m1.close - sl
                if risk <= 0:
                    return []
                tp = m1.close + risk * 2
                if vwap > m1.close:
                    reward_to_vwap = vwap - m1.close
                    if reward_to_vwap >= risk:
                        tp = vwap
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=m1.close,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "seller_absorption_inversion", "target": "VWAP"},
                    )
                )

        if signals:
            self._last_signal_day = ny_day
        return signals
