"""
Strategy 52: Finding The Correct Draw On Liquidity (0.79 Fib DOL)
Source: Faiz SMC ("Finding The Correct Draw On Liquidity With 96% Accuracy..")
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, Position, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.fibonacci import price_at_fib_level
from backtester.indicators.fvg import detect_fvg, get_unmitigated_fvgs
from backtester.indicators.sessions import get_ny_time, is_in_session
from .base import BaseStrategy

FIB_DOL_LEVEL = 0.79
NY_OPEN_HOUR = 9
NY_OPEN_MINUTE = 30


class SessionDolFib(BaseStrategy):
    id = "s052_session_dol_fib"
    name = "Session DOL via 0.79 Fib"
    source_video = "http://www.youtube.com/watch?v=vT_xPTnsZ5s"
    description = (
        "London session range on M15. After a session high/low sweep before NY open, "
        "a 1M close beyond the 0.79 Fibonacci level confirms draw on liquidity. "
        "Entry at the extreme FVG midpoint within the dealing range."
    )
    timeframes = [TF.M15, TF.M1]

    playbook = [
        PlaybookStep(
            step_number=1,
            title="Define London Session Range",
            description="Mark the high and low of the London session on M15.",
            timeframe="M15",
            conditions=["London session 03:00-12:00 NY"],
        ),
        PlaybookStep(
            step_number=2,
            title="Detect Session Sweep",
            description="Wait for a sweep of session high or low before NY open.",
            timeframe="M15",
            conditions=["Sweep must occur before 09:30 NY"],
        ),
        PlaybookStep(
            step_number=3,
            title="Confirm 0.79 Fib DOL",
            description="On M1, wait for a candle close beyond the 0.79 Fib level.",
            timeframe="M1",
            conditions=["Close below 0.79 after high sweep", "Close above 0.79 after low sweep"],
        ),
        PlaybookStep(
            step_number=4,
            title="FVG Entry",
            description="Enter at the 50% midpoint of the extreme FVG in the dealing range.",
            timeframe="M1",
        ),
        PlaybookStep(
            step_number=5,
            title="Risk Management",
            description="SL below dealing range; TP at opposite session liquidity; BE at 1:1.5 RR.",
            timeframe="M1",
        ),
    ]

    def on_start(self):
        self.state = "TRACK_LONDON"
        self.session_high = 0.0
        self.session_low = float("inf")
        self.session_date = None
        self.sweep_side: str | None = None
        self.fib_level = 0.0
        self.dealing_high = 0.0
        self.dealing_low = 0.0
        self.trade_taken_today = False

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m1_bar = bars.get(TF.M1)
        m15_bar = bars.get(TF.M15)
        if not m1_bar or not m15_bar:
            return []

        ny_time = get_ny_time(current_time)
        if self.session_date != ny_time.date() and ny_time.hour == 0:
            self.on_start()
            self.session_date = ny_time.date()

        if self.trade_taken_today:
            return []

        prev_session_high = self.session_high
        prev_session_low = self.session_low

        before_ny_open = ny_time.hour < NY_OPEN_HOUR or (
            ny_time.hour == NY_OPEN_HOUR and ny_time.minute < NY_OPEN_MINUTE
        )

        # Detect sweep against the range established on prior bars
        if (
            self.state == "TRACK_LONDON"
            and before_ny_open
            and prev_session_high > 0
            and prev_session_low < float("inf")
        ):
            if m15_bar.high > prev_session_high:
                self.sweep_side = "high"
                self.fib_level = price_at_fib_level(
                    prev_session_high, prev_session_low, FIB_DOL_LEVEL
                )
                self.dealing_high = m15_bar.high
                self.dealing_low = prev_session_low
                self.state = "WAIT_FIB_CONFIRM"
                self.step_tracker.record(
                    "Session High Swept",
                    2,
                    current_time,
                    m15_bar.high,
                    "M15",
                    f"London high swept. 0.79 Fib at {self.fib_level:.5f}",
                )
            elif m15_bar.low < prev_session_low:
                self.sweep_side = "low"
                self.fib_level = price_at_fib_level(
                    prev_session_low, prev_session_high, FIB_DOL_LEVEL
                )
                self.dealing_high = prev_session_high
                self.dealing_low = m15_bar.low
                self.state = "WAIT_FIB_CONFIRM"
                self.step_tracker.record(
                    "Session Low Swept",
                    2,
                    current_time,
                    m15_bar.low,
                    "M15",
                    f"London low swept. 0.79 Fib at {self.fib_level:.5f}",
                )

        # Track London session range on M15
        if self.state == "TRACK_LONDON" and is_in_session(current_time, "london"):
            self.session_high = max(self.session_high, m15_bar.high)
            self.session_low = min(self.session_low, m15_bar.low)

        if self.state == "TRACK_LONDON":
            return []

        if self.state == "WAIT_FIB_CONFIRM":
            confirmed = False
            if self.sweep_side == "high" and m1_bar.close < self.fib_level:
                confirmed = True
            elif self.sweep_side == "low" and m1_bar.close > self.fib_level:
                confirmed = True

            if confirmed:
                self.state = "WAIT_FVG_ENTRY"
                self.step_tracker.record(
                    "0.79 Fib Confirmed",
                    3,
                    current_time,
                    m1_bar.close,
                    "M1",
                    f"Draw confirmed toward opposite session liquidity.",
                )
            return []

        if self.state == "WAIT_FVG_ENTRY":
            m1_hist = history(self.symbol, TF.M1, 80)
            if len(m1_hist) < 5:
                return []

            fvgs = detect_fvg(m1_hist)
            direction = "bearish" if self.sweep_side == "high" else "bullish"
            candidates = [
                f
                for f in get_unmitigated_fvgs(fvgs, direction)
                if self.dealing_low <= f.midpoint <= self.dealing_high
            ]
            if not candidates:
                entry = m1_bar.close
            else:
                fvg = candidates[-1]
                entry = fvg.midpoint

            if self.sweep_side == "high":
                sl = self.dealing_low - abs(self.dealing_low * 0.0001)
                tp = self.session_low
                if entry <= sl or tp >= entry:
                    return []
                self.trade_taken_today = True
                self.state = "DONE"
                self.step_tracker.record(
                    "FVG Entry",
                    4,
                    current_time,
                    entry,
                    "M1",
                    f"Short at FVG midpoint {entry:.5f}",
                )
                return [
                    Signal(
                        strategy_id=self.id,
                        direction=Direction.SHORT,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        timestamp=current_time,
                        symbol=self.symbol,
                    )
                ]

            sl = self.dealing_high + abs(self.dealing_high * 0.0001)
            tp = self.session_high
            if entry >= sl or tp <= entry:
                return []
            self.trade_taken_today = True
            self.state = "DONE"
            self.step_tracker.record(
                "FVG Entry",
                4,
                current_time,
                entry,
                "M1",
                f"Long at FVG midpoint {entry:.5f}",
            )
            return [
                Signal(
                    strategy_id=self.id,
                    direction=Direction.LONG,
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    timestamp=current_time,
                    symbol=self.symbol,
                )
            ]

        return []

    def on_position_update(
        self,
        bars: dict[TF, Bar],
        history: callable,
        position: Position,
        broker,
        step_tracker,
        current_time: datetime,
    ):
        """Move stop to break-even at 1:1.5 risk-to-reward."""
        if position.break_even_applied:
            return

        m1_bar = bars.get(TF.M1)
        if not m1_bar:
            return

        trade = position.trade
        risk = abs(trade.entry_price - trade.stop_loss)
        if risk <= 0:
            return

        if trade.direction == Direction.LONG:
            target = trade.entry_price + risk * 1.5
            if m1_bar.high >= target:
                broker.move_to_breakeven(self.id, m1_bar, step_tracker)
        else:
            target = trade.entry_price - risk * 1.5
            if m1_bar.low <= target:
                broker.move_to_breakeven(self.id, m1_bar, step_tracker)
