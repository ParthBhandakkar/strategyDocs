"""
Strategy 54: Liquidity Range Trading Strategy (Range Sweep + MSS)
Source: Faiz SMC — video 54 canonical for module `range_sweep_mss`
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, Position, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.order_blocks import detect_order_blocks
from backtester.indicators.sessions import get_ny_time, is_in_session
from backtester.indicators.structure import (
    detect_mss,
    detect_swing_highs,
    detect_swing_lows,
    is_bearish_orderflow,
    is_bullish_orderflow,
)
from .base import BaseStrategy


class RangeSweepMSS(BaseStrategy):
    id = "s054_range_sweep_mss"
    name = "Liquidity Range Sweep + MSS"
    source_video = "http://www.youtube.com/watch?v=LivWGyobZcA"
    description = (
        "5M range-bound liquidity sweep: map range via pullback MSS, sweep a boundary, "
        "confirm MSS + close back inside, enter from order block. Max 3 trades per session."
    )
    timeframes = [TF.M5]

    playbook = [
        PlaybookStep(
            1,
            "Identify Trend",
            "Determine dominant 5M orderflow direction (bullish or bearish).",
            "M5",
        ),
        PlaybookStep(
            2,
            "Map Range",
            "Lock range high/low from impulse leg and pullback MSS.",
            "M5",
        ),
        PlaybookStep(
            3,
            "Wait for Sweep",
            "Price sweeps one range boundary without invalidating the opposite side.",
            "M5",
        ),
        PlaybookStep(
            4,
            "MSS + Close Inside",
            "5M MSS and candle close back inside the range.",
            "M5",
        ),
        PlaybookStep(
            5,
            "Order Block Entry",
            "Enter from the latest unmitigated OB in sweep direction; SL beyond sweep.",
            "M5",
        ),
    ]

    MAX_TRADES_PER_SESSION = 3

    def on_start(self) -> None:
        self.state = "WAIT_TREND"
        self.bias: str | None = None
        self.range_high = 0.0
        self.range_low = 0.0
        self.sweep_extreme = 0.0
        self.trade_direction: Direction | None = None
        self.session_trade_counts: dict[str, int] = {
            "asia": 0,
            "london": 0,
            "new_york": 0,
        }
        self.current_session: str | None = None

    def _active_session(self, utc_time: datetime) -> str | None:
        if is_in_session(utc_time, "asia"):
            return "asia"
        if is_in_session(utc_time, "london"):
            return "london"
        if is_in_session(utc_time, "new_york"):
            return "new_york"
        return None

    def _session_limit_reached(self, session: str | None) -> bool:
        if not session:
            return True
        return self.session_trade_counts.get(session, 0) >= self.MAX_TRADES_PER_SESSION

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        bar = bars.get(TF.M5)
        if not bar:
            return []

        session = self._active_session(current_time)
        if session != self.current_session:
            self.current_session = session
            if session:
                self.state = "WAIT_TREND"
                self.bias = None

        if not session or self._session_limit_reached(session):
            return []

        m5_hist = history(self.symbol, TF.M5, 80)
        if len(m5_hist) < 30:
            return []

        if self.state == "WAIT_TREND":
            if is_bullish_orderflow(m5_hist, lookback=20):
                self.bias = "bullish"
                self.state = "MAP_RANGE"
            elif is_bearish_orderflow(m5_hist, lookback=20):
                self.bias = "bearish"
                self.state = "MAP_RANGE"
            else:
                return []

            sw_highs = detect_swing_highs(m5_hist, lookback=3)
            sw_lows = detect_swing_lows(m5_hist, lookback=3)
            if not sw_highs or not sw_lows:
                self.state = "WAIT_TREND"
                return []

            if self.bias == "bullish":
                self.range_high = sw_highs[-1].price
                shifts = detect_mss(m5_hist, lookback=3)
                bullish_shifts = [s for s in shifts if s.direction == "bullish"]
                if bullish_shifts:
                    self.range_low = min(s.price for s in sw_lows[-4:])
                else:
                    self.range_low = sw_lows[-1].price
            else:
                self.range_low = sw_lows[-1].price
                shifts = detect_mss(m5_hist, lookback=3)
                bearish_shifts = [s for s in shifts if s.direction == "bearish"]
                if bearish_shifts:
                    self.range_high = max(s.price for s in sw_highs[-4:])
                else:
                    self.range_high = sw_highs[-1].price

            if self.range_high <= self.range_low:
                self.state = "WAIT_TREND"
                return []

            self.step_tracker.record(
                "Map Range",
                2,
                current_time,
                bar.close,
                "M5",
                f"Range {self.range_low:.2f}-{self.range_high:.2f} ({self.bias})",
            )
            self.state = "WAIT_SWEEP"
            return []

        if self.state == "WAIT_SWEEP":
            if self.bias == "bullish":
                if bar.low < self.range_low:
                    self.state = "WAIT_TREND"
                    return []
                if bar.high > self.range_high:
                    self.sweep_extreme = bar.high
                    self.trade_direction = Direction.SHORT
                    self.state = "WAIT_MSS"
            elif self.bias == "bearish":
                if bar.high > self.range_high:
                    self.state = "WAIT_TREND"
                    return []
                if bar.low < self.range_low:
                    self.sweep_extreme = bar.low
                    self.trade_direction = Direction.LONG
                    self.state = "WAIT_MSS"
            return []

        if self.state == "WAIT_MSS" and self.trade_direction is not None:
            if self.trade_direction == Direction.SHORT:
                self.sweep_extreme = max(self.sweep_extreme, bar.high)
                inside = bar.close < self.range_high
                mss_ok = any(s.direction == "bearish" for s in detect_mss(m5_hist, lookback=2))
            else:
                self.sweep_extreme = min(self.sweep_extreme, bar.low)
                inside = bar.close > self.range_low
                mss_ok = any(s.direction == "bullish" for s in detect_mss(m5_hist, lookback=2))

            if inside and mss_ok:
                obs = detect_order_blocks(m5_hist[-12:])
                entry_price = bar.close
                if self.trade_direction == Direction.SHORT:
                    bear_obs = [o for o in obs if o.direction == "bearish"]
                    if bear_obs:
                        entry_price = bear_obs[-1].midpoint
                    sl = self.sweep_extreme + abs(self.sweep_extreme) * 0.0001
                    tp = self.range_low
                    signal = Signal(
                        self.id,
                        Direction.SHORT,
                        entry_price,
                        sl,
                        tp,
                        current_time,
                        self.symbol,
                    )
                else:
                    bull_obs = [o for o in obs if o.direction == "bullish"]
                    if bull_obs:
                        entry_price = bull_obs[-1].midpoint
                    sl = self.sweep_extreme - abs(self.sweep_extreme) * 0.0001
                    tp = self.range_high
                    signal = Signal(
                        self.id,
                        Direction.LONG,
                        entry_price,
                        sl,
                        tp,
                        current_time,
                        self.symbol,
                    )

                self.step_tracker.record(
                    "MSS Entry",
                    4,
                    current_time,
                    entry_price,
                    "M5",
                    f"{self.trade_direction.value} after sweep + MSS",
                )
                if session:
                    self.session_trade_counts[session] = (
                        self.session_trade_counts.get(session, 0) + 1
                    )
                self.state = "WAIT_TREND"
                self.bias = None
                self.trade_direction = None
                return [signal]

        return []

    def on_position_update(
        self,
        bars: dict[TF, Bar],
        history: callable,
        position: Position,
        broker,
        step_tracker,
        current_time: datetime,
    ) -> None:
        """Move stop to break-even at 1:1.5 risk-to-reward."""
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
            target = trade.entry_price + risk * 1.5
            if bar.high >= target:
                broker.move_to_breakeven(self.id, bar, step_tracker)
        else:
            target = trade.entry_price - risk * 1.5
            if bar.low <= target:
                broker.move_to_breakeven(self.id, bar, step_tracker)
