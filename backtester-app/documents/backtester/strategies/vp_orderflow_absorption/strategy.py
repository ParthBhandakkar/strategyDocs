"""
Video #1 — VP + Orderflow Absorption (canonical cluster A).
Fade absorption at developing VP extremes; enter on order-cluster inversion.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml

from backtester.core import Bar, Direction, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.orderflow import (
    is_buyer_absorption,
    is_seller_absorption,
    session_vwap,
)
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.structure import detect_swing_highs, detect_swing_lows
from backtester.indicators.volume_profile import compute_frvp
from backtester.strategies.base import BaseStrategy

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing NY-session VP extremes when wick volume "
        "shows failed aggression and price inverts a local order cluster."
    )
    timeframes = [TF.M1, TF.D1]
    extra_symbols = []

    playbook = [
        PlaybookStep(
            1,
            "Developing VP",
            "Build session VP/VWAP after 9:30 NY open.",
            "M1",
            conditions=["Post NY open", "Session bars only"],
            key_levels=["POC", "VAH", "VAL", "VWAP"],
        ),
        PlaybookStep(
            2,
            "Absorption",
            "Identify buyer/seller absorption at VP extremes via wick volume.",
            "M1",
        ),
        PlaybookStep(
            3,
            "Cluster Inversion",
            "Enter when price closes through the proximate swing cluster.",
            "M1",
        ),
    ]

    def on_start(self):
        cfg = _load_config().get("parameters", {})
        self.absorption_volume_mult = float(cfg.get("absorption_volume_mult", 1.5))
        self.absorption_wick_ratio = float(cfg.get("absorption_wick_ratio", 0.45))
        self.cluster_lookback = int(cfg.get("cluster_lookback_bars", 12))
        self.vp_proximity_pct = float(cfg.get("vp_proximity_pct", 0.15))
        self.pending_short_cluster: float | None = None
        self.pending_long_cluster: float | None = None
        self.absorption_high: float | None = None
        self.absorption_low: float | None = None
        self.session_date = None

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: Callable[[str | None, TF | None, int], list[Bar]],
        multi_symbol_bars: dict[str, dict[TF, Bar]],
        current_time: datetime,
    ) -> list[Signal]:
        m1_bar = bars.get(TF.M1)
        if not m1_bar:
            return []

        if not is_in_session(current_time, "new_york"):
            return []

        ny_time = get_ny_time(current_time)
        if ny_time.time().hour == 9 and ny_time.time().minute < 30:
            return []

        m1_hist = history(self.symbol, TF.M1, 500)
        if len(m1_hist) < 30:
            return []

        session_bars = self._session_bars(m1_hist, current_time)
        if len(session_bars) < 20:
            return []

        vp = compute_frvp(session_bars)
        if vp is None:
            return []

        vwap = session_vwap(session_bars)
        avg_volume = sum(b.tick_volume for b in m1_hist[-20:]) / 20.0
        signals: list[Signal] = []

        near_vah = self._near_level(m1_bar.close, vp.vah, session_bars)
        near_poc_vwap = self._near_level(m1_bar.close, vp.poc, session_bars) or self._near_level(
            m1_bar.close, vwap, session_bars
        )

        if near_vah or near_poc_vwap:
            if is_buyer_absorption(
                m1_bar,
                avg_volume,
                min_wick_ratio=self.absorption_wick_ratio,
                min_volume_mult=self.absorption_volume_mult,
            ):
                cluster = self._nearest_swing_low(m1_hist[:-1])
                if cluster is not None:
                    self.pending_short_cluster = cluster
                    self.absorption_high = m1_bar.high
                    if self.step_tracker:
                        self.step_tracker.record(
                            "Buyer Absorption",
                            2,
                            current_time,
                            m1_bar.high,
                            "M1",
                            f"Absorption near VP high; cluster {cluster:.5f}",
                        )

        below_val = m1_bar.close < vp.val
        if below_val and is_seller_absorption(
            m1_bar,
            avg_volume,
            min_wick_ratio=self.absorption_wick_ratio,
            min_volume_mult=self.absorption_volume_mult,
        ):
            cluster = self._nearest_swing_high(m1_hist[:-1])
            if cluster is not None:
                self.pending_long_cluster = cluster
                self.absorption_low = m1_bar.low
                if self.step_tracker:
                    self.step_tracker.record(
                        "Seller Absorption",
                        2,
                        current_time,
                        m1_bar.low,
                        "M1",
                        f"Absorption below VAL; cluster {cluster:.5f}",
                    )

        if self.pending_short_cluster is not None and self.absorption_high is not None:
            if m1_bar.close < self.pending_short_cluster and m1_bar.is_bearish:
                entry = m1_bar.close
                stop = self.absorption_high
                risk = stop - entry
                if risk > 0:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.SHORT,
                            entry_price=entry,
                            stop_loss=stop,
                            take_profit=entry - risk,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "short_vp_absorption", "target": "val", "tp_level": vp.val},
                        )
                    )
                self.pending_short_cluster = None
                self.absorption_high = None

        if self.pending_long_cluster is not None and self.absorption_low is not None:
            if m1_bar.close > self.pending_long_cluster and m1_bar.is_bullish:
                entry = m1_bar.close
                stop = self.absorption_low
                risk = entry - stop
                if risk > 0:
                    signals.append(
                        Signal(
                            strategy_id=self.id,
                            direction=Direction.LONG,
                            entry_price=entry,
                            stop_loss=stop,
                            take_profit=entry + risk * 2,
                            timestamp=current_time,
                            symbol=self.symbol,
                            metadata={"setup": "long_vp_absorption", "target": "vwap", "tp_level": vwap},
                        )
                    )
                self.pending_long_cluster = None
                self.absorption_low = None

        return signals

    def _session_bars(self, m1_hist: list[Bar], current_time: datetime) -> list[Bar]:
        ny_date = get_ny_time(current_time).date()
        if self.session_date != ny_date:
            self.session_date = ny_date
            self.pending_short_cluster = None
            self.pending_long_cluster = None
            self.absorption_high = None
            self.absorption_low = None

        session: list[Bar] = []
        for bar in m1_hist:
            ny = get_ny_time(bar.time)
            if ny.date() != ny_date:
                continue
            if ny.time().hour < 9 or (ny.time().hour == 9 and ny.time().minute < 30):
                continue
            if bar.time <= current_time:
                session.append(bar)
        return session

    def _near_level(self, price: float, level: float, session_bars: list[Bar]) -> bool:
        if not session_bars:
            return False
        session_range = max(b.high for b in session_bars) - min(b.low for b in session_bars)
        if session_range <= 0:
            return False
        return abs(price - level) <= session_range * self.vp_proximity_pct

    def _nearest_swing_low(self, bars: list[Bar]) -> float | None:
        lookback = bars[-self.cluster_lookback :] if len(bars) > self.cluster_lookback else bars
        swings = detect_swing_lows(lookback, lookback=2)
        if not swings:
            return min(b.low for b in lookback)
        return swings[-1].price

    def _nearest_swing_high(self, bars: list[Bar]) -> float | None:
        lookback = bars[-self.cluster_lookback :] if len(bars) > self.cluster_lookback else bars
        swings = detect_swing_highs(lookback, lookback=2)
        if not swings:
            return max(b.high for b in lookback)
        return swings[-1].price
