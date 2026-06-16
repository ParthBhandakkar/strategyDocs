"""VP Orderflow Absorption strategy (Video #1)."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from backtester.core import Bar, Signal, Direction, PlaybookStep
from backtester.core.timeframes import TF
from backtester.indicators.sessions import get_ny_time, is_post_ny_open
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy
from backtester.strategies.vp_orderflow_absorption.helpers import (
    detect_buyer_absorption,
    detect_seller_absorption,
    find_recent_support_cluster,
    find_recent_resistance_cluster,
)


class VPOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade failed absorption at developing session VP extremes when aggressive "
        "volume stalls in wicks and price inverts local order clusters."
    )
    timeframes = [TF.M1, TF.M5]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Session VP Setup",
            description="Build developing NY session volume profile from M1 bars after 9:30 NY.",
            timeframe="M1",
            conditions=["Post 9:30 NY", "Track POC/VAH/VAL"],
            key_levels=["POC", "VAH", "VAL", "VWAP proxy"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption Detection",
            description="Identify wick-trapped aggressive volume without follow-through.",
            timeframe="M1",
            conditions=["Upper wick buyer absorption at VAH/POC", "Lower wick seller absorption at VAL"],
        ),
        PlaybookStep(
            step_number=3,
            title="Order Inversion Entry",
            description="Enter on close through nearby support/resistance cluster.",
            timeframe="M1",
            conditions=["Short below support after buyer absorption", "Long above resistance after seller absorption"],
        ),
    ]

    def on_start(self):
        self._session_date = None
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None
        self._last_signal_bar: datetime | None = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable,
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        m1 = bars.get(TF.M1)
        if m1 is None or not is_post_ny_open(current_time):
            return []

        ny_date = get_ny_time(current_time).date()
        if self._session_date != ny_date:
            self._session_date = ny_date
            self._pending_short = None
            self._pending_long = None

        m1_hist = history(None, TF.M1, 500)
        session_bars = [
            b for b in m1_hist
            if get_ny_time(b.time).date() == ny_date and is_post_ny_open(b.time)
        ]
        if len(session_bars) < 30:
            return []

        vp = compute_frvp(session_bars[-240:], row_size=80)
        if vp is None:
            return []

        vwap_proxy = sum(b.close * max(b.tick_volume, 1) for b in session_bars) / max(
            sum(max(b.tick_volume, 1) for b in session_bars), 1
        )

        signals: list[Signal] = []
        if self._last_signal_bar == m1.time:
            return []

        recent = session_bars[-12:]
        prev = recent[:-1] if len(recent) > 1 else []

        # Short setup: buyer absorption near VAH/POC/VWAP
        near_premium = (
            m1.high >= min(vp.vah, vp.poc) * 0.9995
            or m1.high >= vwap_proxy * 0.9995
        )
        if prev and near_premium:
            absorption_bar = prev[-1]
            if detect_buyer_absorption(absorption_bar):
                support = find_recent_support_cluster(prev)
                if support is not None:
                    self._pending_short = {
                        "support": support,
                        "stop": absorption_bar.high,
                        "target": vp.val,
                    }

        if self._pending_short and m1.close < self._pending_short["support"]:
            stop = self._pending_short["stop"]
            entry = m1.close
            risk = stop - entry
            if risk > 0:
                target = self._pending_short["target"]
                if target >= entry:
                    target = entry - risk
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=target,
                        timestamp=m1.time,
                        symbol=self.symbol,
                        metadata={"setup": "buyer_absorption_inversion"},
                    )
                )
                self._pending_short = None
                self._last_signal_bar = m1.time

        # Long setup: seller absorption below VAL
        near_discount = m1.low <= vp.val * 1.0005
        if prev and near_discount and not signals:
            absorption_bar = prev[-1]
            if detect_seller_absorption(absorption_bar):
                resistance = find_recent_resistance_cluster(prev)
                if resistance is not None:
                    self._pending_long = {
                        "resistance": resistance,
                        "stop": absorption_bar.low,
                        "target": vwap_proxy,
                    }

        if self._pending_long and m1.close > self._pending_long["resistance"] and not signals:
            stop = self._pending_long["stop"]
            entry = m1.close
            risk = entry - stop
            if risk > 0:
                target = self._pending_long["target"]
                if target <= entry:
                    target = entry + risk * 2
                signals.append(
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.LONG,
                        entry_price=entry,
                        stop_loss=stop,
                        take_profit=target,
                        timestamp=m1.time,
                        symbol=self.symbol,
                        metadata={"setup": "seller_absorption_inversion"},
                    )
                )
                self._pending_long = None
                self._last_signal_bar = m1.time

        return signals
