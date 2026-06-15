"""
Strategy 54: Liquidity Range Trading Strategy (Range Sweep + MSS)
Source: Faiz SMC ("The Only Liquidity Strategy You'll Ever Need")
Canonical module: range_sweep_mss (cluster Q)
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, Position, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.sessions import is_in_session
from backtester.indicators.structure import (
    detect_mss,
    detect_swing_highs,
    detect_swing_lows,
    is_bullish_orderflow,
    is_bearish_orderflow,
)
from backtester.indicators.order_blocks import detect_order_blocks
from .base import BaseStrategy


class RangeSweepMSS(BaseStrategy):
    id = "s054_range_sweep_mss"
    name = "Range Sweep + MSS (5M)"
    source_video = "http://www.youtube.com/watch?v=LivWGyobZcA"
    description = (
        "5M range-bound liquidity sweep: map range via MSS in pullback, "
        "sweep boundary, MSS + close inside range, enter on auto/breaker block. "
        "Max 3 trades per session (Asia/London/NY)."
    )
    timeframes = [TF.M5]

    playbook = [
        PlaybookStep(
            1,
            "Identify Trend",
            "Determine dominant 5M orderflow (bullish or bearish).",
            "M5",
        ),
        PlaybookStep(
            2,
            "Map Range",
            "Range high from impulse; range low from MSS inside pullback (or inverse in downtrend).",
            "M5",
        ),
        PlaybookStep(
            3,
            "Wait for Sweep",
            "Price sweeps one boundary without invalidating the opposite side first.",
            "M5",
        ),
        PlaybookStep(
            4,
            "MSS + Close Inside",
            "5M MSS and candle close back inside the range boundaries.",
            "M5",
        ),
        PlaybookStep(
            5,
            "Auto Block Entry",
            "Enter on the auto/breaker block after confirmation; target opposite range boundary.",
            "M5",
        ),
    ]

    MAX_TRADES_PER_SESSION = 3

    def on_start(self):
        self.state = "WAIT_TREND"
        self.bias: str | None = None
        self.range_high = 0.0
        self.range_low = 0.0
        self.sweep_extreme = 0.0
        self.session_trade_counts: dict[str, int] = {}
        self.current_session = ""

    def _active_session(self, current_time: datetime) -> str:
        if is_in_session(current_time, "asia"):
            return "asia"
        if is_in_session(current_time, "london"):
            return "london"
        if is_in_session(current_time, "new_york"):
            return "new_york"
        return ""

    def _session_trade_count(self, session: str) -> int:
        return self.session_trade_counts.get(session, 0)

    def _record_session_trade(self, session: str):
        self.session_trade_counts[session] = self._session_trade_count(session) + 1

    def _reset_setup(self):
        self.state = "WAIT_TREND"
        self.bias = None
        self.range_high = 0.0
        self.range_low = 0.0
        self.sweep_extreme = 0.0

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        bar = bars.get(TF.M5)
        if not bar:
            return []

        session = self._active_session(current_time)
        if not session:
            return []

        if session != self.current_session:
            self.current_session = session

        if self._session_trade_count(session) >= self.MAX_TRADES_PER_SESSION:
            return []

        hist = history(self.symbol, TF.M5, 80)
        if len(hist) < 30:
            return []

        if self.state == "WAIT_TREND":
            if is_bullish_orderflow(hist, lookback=20):
                self.bias = "bullish"
                self.state = "MAP_RANGE"
            elif is_bearish_orderflow(hist, lookback=20):
                self.bias = "bearish"
                self.state = "MAP_RANGE"
            return []

        if self.state == "MAP_RANGE":
            swings_high = detect_swing_highs(hist, lookback=3)
            swings_low = detect_swing_lows(hist, lookback=3)
            shifts = detect_mss(hist, lookback=3)

            if self.bias == "bullish" and swings_high and swings_low and shifts:
                self.range_high = swings_high[-1].price
                bearish_shifts = [s for s in shifts if s.direction == "bearish"]
                if bearish_shifts:
                    self.range_low = min(swings_low[-3:], key=lambda s: s.price).price
                    self.state = "WAIT_SWEEP"
                    self.step_tracker.record(
                        "Map Range",
                        2,
                        bar.time,
                        self.range_high,
                        "M5",
                        f"Bullish range H={self.range_high:.5f} L={self.range_low:.5f}",
                    )

            elif self.bias == "bearish" and swings_high and swings_low and shifts:
                self.range_low = swings_low[-1].price
                bullish_shifts = [s for s in shifts if s.direction == "bullish"]
                if bullish_shifts:
                    self.range_high = max(swings_high[-3:], key=lambda s: s.price).price
                    self.state = "WAIT_SWEEP"
                    self.step_tracker.record(
                        "Map Range",
                        2,
                        bar.time,
                        self.range_low,
                        "M5",
                        f"Bearish range H={self.range_high:.5f} L={self.range_low:.5f}",
                    )
            return []

        if self.state == "WAIT_SWEEP":
            if self.range_high <= self.range_low:
                self._reset_setup()
                return []

            if self.bias == "bullish":
                if bar.high > self.range_high:
                    self._reset_setup()
                elif bar.low < self.range_low:
                    self.state = "WAIT_MSS_INSIDE"
                    self.sweep_extreme = bar.low
                    self.step_tracker.record(
                        "Sweep Low",
                        3,
                        bar.time,
                        bar.low,
                        "M5",
                        "Swept range low without breaking high first.",
                    )

            elif self.bias == "bearish":
                if bar.low < self.range_low:
                    self._reset_setup()
                elif bar.high > self.range_high:
                    self.state = "WAIT_MSS_INSIDE"
                    self.sweep_extreme = bar.high
                    self.step_tracker.record(
                        "Sweep High",
                        3,
                        bar.time,
                        bar.high,
                        "M5",
                        "Swept range high without breaking low first.",
                    )
            return []

        if self.state == "WAIT_MSS_INSIDE":
            recent_shifts = detect_mss(hist[-25:], lookback=2)

            if self.bias == "bullish":
                self.sweep_extreme = min(self.sweep_extreme, bar.low)
                bullish_shift = any(s.direction == "bullish" for s in recent_shifts)
                inside = self.range_low < bar.close < self.range_high
                if bullish_shift and inside and bar.is_bullish:
                    return self._enter_long(bar, session, hist)

            elif self.bias == "bearish":
                self.sweep_extreme = max(self.sweep_extreme, bar.high)
                bearish_shift = any(s.direction == "bearish" for s in recent_shifts)
                inside = self.range_low < bar.close < self.range_high
                if bearish_shift and inside and bar.is_bearish:
                    return self._enter_short(bar, session, hist)

        return []

    def _enter_long(self, bar: Bar, session: str, hist: list[Bar]) -> list[Signal]:
        obs = detect_order_blocks(hist[-15:])
        bullish_obs = [ob for ob in obs if ob.direction == "bullish" and not ob.mitigated]
        sl = self.sweep_extreme - abs(self.sweep_extreme * 0.0001)
        if bullish_obs:
            sl = min(sl, bullish_obs[-1].low)
        tp = self.range_high
        if bar.close <= sl or tp <= bar.close:
            self._reset_setup()
            return []

        self._record_session_trade(session)
        self.state = "DONE"
        self.step_tracker.record(
            "Long Entry",
            5,
            bar.time,
            bar.close,
            "M5",
            "Bullish MSS inside range; auto block entry.",
        )
        return [
            Signal(
                self.id,
                Direction.LONG,
                bar.close,
                sl,
                tp,
                bar.time,
                self.symbol,
            )
        ]

    def _enter_short(self, bar: Bar, session: str, hist: list[Bar]) -> list[Signal]:
        obs = detect_order_blocks(hist[-15:])
        bearish_obs = [ob for ob in obs if ob.direction == "bearish" and not ob.mitigated]
        sl = self.sweep_extreme + abs(self.sweep_extreme * 0.0001)
        if bearish_obs:
            sl = max(sl, bearish_obs[-1].high)
        tp = self.range_low
        if bar.close >= sl or tp >= bar.close:
            self._reset_setup()
            return []

        self._record_session_trade(session)
        self.state = "DONE"
        self.step_tracker.record(
            "Short Entry",
            5,
            bar.time,
            bar.close,
            "M5",
            "Bearish MSS inside range; auto block entry.",
        )
        return [
            Signal(
                self.id,
                Direction.SHORT,
                bar.close,
                sl,
                tp,
                bar.time,
                self.symbol,
            )
        ]

    def on_position_update(
        self,
        bars: dict[TF, Bar],
        history,
        position: Position,
        broker,
        step_tracker,
        current_time: datetime,
    ):
        """Move stop to break-even at 1:1.5 RR."""
        if position.break_even_applied:
            return

        bar = bars.get(TF.M5)
        if not bar:
            return

        trade = position.trade
        risk = abs(trade.entry_price - trade.stop_loss)
        if risk <= 0:
            return

        if trade.direction == Direction.LONG:
            be_trigger = trade.entry_price + risk * 1.5
            if bar.high >= be_trigger:
                broker.move_to_breakeven(self.id, bar, step_tracker)
        else:
            be_trigger = trade.entry_price - risk * 1.5
            if bar.low <= be_trigger:
                broker.move_to_breakeven(self.id, bar, step_tracker)
