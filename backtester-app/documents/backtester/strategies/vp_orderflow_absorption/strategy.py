"""
VP + Orderflow Absorption — fade failed aggression at developing VP extremes.
Video #1 canonical module.
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Direction, OrderType, PlaybookStep, Signal
from backtester.core.timeframes import TF
from backtester.indicators.orderflow import (
    average_volume,
    buyer_absorption,
    recent_swing_high,
    recent_swing_low,
    seller_absorption,
)
from backtester.indicators.sessions import get_ny_time, is_post_ny_open
from backtester.indicators.volume_profile import VolumeProfile, compute_frvp
from backtester.strategies.base import BaseStrategy


class VpOrderflowAbsorption(BaseStrategy):
    id = "s001_vp_orderflow_absorption"
    name = "VP + Orderflow Absorption"
    source_video = "1"
    description = (
        "Fade absorption at developing VP extremes when aggressive orders fail "
        "at wicks and price inverts order clusters after NY open."
    )
    timeframes = [TF.M1]
    extra_symbols = []
    playbook = [
        PlaybookStep(
            step_number=1,
            title="Developing VP",
            description="Build session VP from 9:30 NY M1 bars (POC/VAH/VAL/VWAP).",
            timeframe="M1",
            conditions=["Post 9:30 NY", "Session developing profile"],
            key_levels=["POC", "VAH", "VAL", "VWAP"],
        ),
        PlaybookStep(
            step_number=2,
            title="Absorption",
            description="Detect buyer/seller absorption via wick volume clusters.",
            timeframe="M1",
            conditions=["Wick-dominant candle", "Volume spike vs session avg"],
        ),
        PlaybookStep(
            step_number=3,
            title="Inversion Entry",
            description="Enter on close through nearby order cluster (swing proxy).",
            timeframe="M1",
            conditions=["Short below cluster after buyer absorption at VAH/POC"],
        ),
    ]

    def on_start(self):
        self._session_day = None
        self._session_bars: list[Bar] = []
        self._pending_short: dict | None = None
        self._pending_long: dict | None = None
        self._vp: VolumeProfile | None = None
        self._vwap_num = 0.0
        self._vwap_den = 0.0

    def on_bar(self, bars, history, multi_symbol_bars, current_time):
        if TF.M1 not in bars:
            return []

        bar = bars[TF.M1]
        if not is_post_ny_open(current_time):
            return []

        ny_date = get_ny_time(current_time).date()
        if self._session_day != ny_date:
            self._reset_session(ny_date)

        self._session_bars.append(bar)
        self._update_vwap(bar)
        self._vp = compute_frvp(self._session_bars, row_size=80)
        if self._vp is None:
            return []

        m1_hist = history(None, TF.M1, 30)
        avg_vol = average_volume(m1_hist[:-1] if len(m1_hist) > 1 else m1_hist)
        signals: list[Signal] = []

        vwap = self._vwap()
        near_vah = abs(bar.close - self._vp.vah) <= self._tolerance(bar)
        near_poc = abs(bar.close - self._vp.poc) <= self._tolerance(bar)
        near_vwap = abs(bar.close - vwap) <= self._tolerance(bar)
        below_val = bar.close < self._vp.val

        if buyer_absorption(bar, avg_vol) and (near_vah or near_poc or near_vwap):
            cluster_low = recent_swing_low(m1_hist[:-1], lookback=6)
            self._pending_short = {
                "cluster_low": cluster_low,
                "absorption_high": bar.high,
                "target": self._vp.val,
            }

        if self._pending_short and bar.close < self._pending_short["cluster_low"]:
            sl = self._pending_short["absorption_high"] + self._tolerance(bar)
            entry = bar.close
            tp = self._pending_short["target"]
            if entry < sl and tp < entry:
                signals.append(
                    self._make_signal(
                        Direction.SHORT,
                        entry,
                        sl,
                        tp,
                        current_time,
                        "short_absorption_inversion",
                    )
                )
            self._pending_short = None

        if seller_absorption(bar, avg_vol) and below_val:
            cluster_high = recent_swing_high(m1_hist[:-1], lookback=6)
            self._pending_long = {
                "cluster_high": cluster_high,
                "absorption_low": bar.low,
                "target": vwap if vwap > bar.close else self._vp.poc,
            }

        if self._pending_long and bar.close > self._pending_long["cluster_high"]:
            sl = self._pending_long["absorption_low"] - self._tolerance(bar)
            entry = bar.close
            tp = self._pending_long["target"]
            if entry > sl and tp > entry:
                signals.append(
                    self._make_signal(
                        Direction.LONG,
                        entry,
                        sl,
                        tp,
                        current_time,
                        "long_absorption_inversion",
                    )
                )
            self._pending_long = None

        return signals

    def _reset_session(self, ny_date):
        self._session_day = ny_date
        self._session_bars = []
        self._pending_short = None
        self._pending_long = None
        self._vp = None
        self._vwap_num = 0.0
        self._vwap_den = 0.0

    def _update_vwap(self, bar: Bar):
        typical = (bar.high + bar.low + bar.close) / 3.0
        vol = bar.tick_volume or 1
        self._vwap_num += typical * vol
        self._vwap_den += vol

    def _vwap(self) -> float:
        if self._vwap_den <= 0:
            return self._session_bars[-1].close if self._session_bars else 0.0
        return self._vwap_num / self._vwap_den

    def _tolerance(self, bar: Bar) -> float:
        return max(bar.total_range * 0.15, self._pip_buffer())

    def _pip_buffer(self) -> float:
        sym = self.symbol.upper()
        if "XAU" in sym:
            return 0.5
        if "JPY" in sym:
            return 0.05
        return 0.0005

    def _make_signal(
        self,
        direction: Direction,
        entry: float,
        sl: float,
        tp: float,
        timestamp: datetime,
        setup: str,
    ) -> Signal:
        return Signal(
            strategy_id=self.id,
            direction=direction,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            timestamp=timestamp,
            symbol=self.symbol,
            order_type=OrderType.MARKET,
            metadata={"setup": setup},
        )
