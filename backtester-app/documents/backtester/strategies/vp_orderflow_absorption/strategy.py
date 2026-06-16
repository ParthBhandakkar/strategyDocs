"""
Video #1 — Orderflow and Volume Profile absorption at developing VP extremes.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import is_in_session
from backtester.strategies.base import BaseStrategy
from .helpers import (
    SessionProfile,
    average_volume,
    compute_session_profile,
    is_buyer_absorption,
    is_seller_absorption,
    near_level,
    session_bars_since_ny_open,
)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing NY session volume profile extremes. "
        "Proxy orderflow uses tick_volume wick absorption; entries trigger on "
        "M1 close through local support/resistance clusters."
    )
    timeframes = [TF.M1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Session VP",
            "Build developing volume profile from 9:30 NY M1 bars (POC/VAH/VAL/VWAP).",
            "M1",
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Identify buyer absorption above VAH/VWAP or seller absorption below VAL.",
            "M1",
        ),
        PlaybookStep(
            3,
            "Inversion Trigger",
            "Enter when M1 closes through the local order cluster (support/resistance flip).",
            "M1",
        ),
        PlaybookStep(
            4,
            "Risk",
            "Stop beyond absorption wick; target VAL for shorts and VWAP for longs.",
            "M1",
        ),
    ]

    def on_start(self):
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None
        self._last_session_day: datetime | None = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if not m1:
            return []

        if not is_in_session(current_time, "new_york"):
            return []

        m1_hist = history(self.symbol, TF.M1, 120)
        if len(m1_hist) < 30:
            return []

        session_bars = session_bars_since_ny_open(m1_hist, current_time)
        session_profile = compute_session_profile(session_bars)
        if session_profile is None:
            return []

        avg_vol = average_volume(m1_hist, lookback=30)
        poc = session_profile.profile.poc
        vah = session_profile.profile.vah
        val = session_profile.profile.val
        vwap = session_profile.vwap

        recent = m1_hist[-6:-1]
        if recent:
            cluster_support = min(b.low for b in recent)
            cluster_resistance = max(b.high for b in recent)
        else:
            cluster_support = m1.low
            cluster_resistance = m1.high

        signals: list[Signal] = []

        at_premium = (
            near_level(m1.high, vah)
            or near_level(m1.high, poc)
            or near_level(m1.high, vwap)
            or m1.close > vah
        )
        if at_premium and is_buyer_absorption(m1, avg_vol):
            self._pending_short = {
                "cluster": cluster_support,
                "stop": m1.high,
                "target": val,
                "time": current_time,
            }

        at_discount = near_level(m1.low, val) or m1.close < val
        if at_discount and is_seller_absorption(m1, avg_vol):
            self._pending_long = {
                "cluster": cluster_resistance,
                "stop": m1.low,
                "target": vwap,
                "time": current_time,
            }

        if self._pending_short and m1.is_bearish and m1.close < self._pending_short["cluster"]:
            stop = self._pending_short["stop"]
            entry = m1.close
            target = self._pending_short["target"]
            risk = stop - entry
            if risk > 0 and target < entry:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=target,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "buyer_absorption_vah", "vah": vah, "val": val},
                    )
                )
            self._pending_short = None

        if self._pending_long and m1.is_bullish and m1.close > self._pending_long["cluster"]:
            stop = self._pending_long["stop"]
            entry = m1.close
            target = self._pending_long["target"]
            risk = entry - stop
            if risk > 0 and target > entry:
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=target,
                        timestamp=current_time,
                        symbol=self.symbol,
                        metadata={"setup": "seller_absorption_val", "vah": vah, "val": val},
                    )
                )
            self._pending_long = None

        return signals
