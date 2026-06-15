"""
Strategy 52: Finding Correct Draw on Liquidity (0.79 Fib)
Source: Faiz SMC ("Finding The Correct Draw On Liquidity With 96% Accuracy")
Canonical module: session_dol_fib
"""

from __future__ import annotations

from datetime import datetime

from backtester.core import Bar, Signal, Position, PlaybookStep, Direction
from backtester.core.timeframes import TF
from backtester.indicators.fibonacci import price_at_fib_level
from backtester.indicators.fvg import detect_fvg
from backtester.indicators.sessions import get_ny_time, is_in_session
from .base import BaseStrategy

FIB_DOL_LEVEL = 0.79


class SessionDOLFib(BaseStrategy):
    id = "s052_session_dol_fib"
    name = "Session DOL via 0.79 Fib"
    source_video = "http://www.youtube.com/watch?v=vT_xPTnsZ5s"
    description = (
        "London session 15M range sweep before NY open; 1M close beyond 0.79 Fib "
        "confirms draw on liquidity; enter at extreme FVG midpoint in dealing range."
    )
    timeframes = [TF.M15, TF.M1]

    playbook = [
        PlaybookStep(
            step_number=1,
            title="Define London Session Range",
            description="Mark London session high/low on M15.",
            timeframe="M15",
            conditions=["Session == London", "Before 9:30 NY"],
        ),
        PlaybookStep(
            step_number=2,
            title="Detect Liquidity Sweep",
            description="Wait for sweep of session high or low before NY open.",
            timeframe="M15",
        ),
        PlaybookStep(
            step_number=3,
            title="Apply 0.79 Fib Filter",
            description="Draw Fib from swept extreme to opposite boundary; require M1 close beyond 0.79.",
            timeframe="M1",
        ),
        PlaybookStep(
            step_number=4,
            title="FVG Entry",
            description="Enter at 50% of extreme FVG within dealing range.",
            timeframe="M1",
        ),
        PlaybookStep(
            step_number=5,
            title="Risk Management",
            description="SL beyond dealing range; TP at opposite session liquidity; BE at 1:1.5.",
            timeframe="M1",
        ),
    ]

    def on_start(self) -> None:
        self.session_high = 0.0
        self.session_low = float("inf")
        self.session_date = None
        self.sweep_side: str | None = None
        self.fib_level_price = 0.0
        self.dol_target = 0.0
        self.dealing_high = 0.0
        self.dealing_low = 0.0
        self.bias_confirmed = False
        self.trade_taken_today = False

    def on_bar(
        self,
        bars: dict[TF, Bar],
        history: callable,
        multi_symbol_bars: dict,
        current_time: datetime,
    ) -> list[Signal]:
        m15 = bars.get(TF.M15)
        m1 = bars.get(TF.M1)
        if not m15 or not m1:
            return []

        ny_time = get_ny_time(current_time)
        if self.session_date != ny_time.date() and ny_time.hour == 0:
            self.on_start()
            self.session_date = ny_time.date()

        if self.trade_taken_today:
            return []

        # Only trade before NY open per spec.
        if ny_time.hour > 9 or (ny_time.hour == 9 and ny_time.minute >= 30):
            return []

        # Build London session range on M15.
        if is_in_session(current_time, "london"):
            if self.session_high == 0.0:
                self.session_high = m15.high
                self.session_low = m15.low
            else:
                self.session_high = max(self.session_high, m15.high)
                self.session_low = min(self.session_low, m15.low)

        if self.session_high <= 0 or self.session_low == float("inf"):
            return []

        # Step 2: detect sweep of session boundary.
        if self.sweep_side is None:
            if m15.high > self.session_high:
                self.sweep_side = "high"
                self.dealing_high = m15.high
                self.dealing_low = self.session_low
                self.dol_target = self.session_low
                self.fib_level_price = price_at_fib_level(
                    self.dealing_high, self.dealing_low, FIB_DOL_LEVEL
                )
                self.step_tracker.record(
                    "Session High Swept", 2, m15.time, m15.high, "M15",
                    f"High swept. 0.79 Fib @ {self.fib_level_price:.5f}",
                )
            elif m15.low < self.session_low:
                self.sweep_side = "low"
                self.dealing_high = self.session_high
                self.dealing_low = m15.low
                self.dol_target = self.session_high
                self.fib_level_price = price_at_fib_level(
                    self.dealing_high, self.dealing_low, FIB_DOL_LEVEL
                )
                self.step_tracker.record(
                    "Session Low Swept", 2, m15.time, m15.low, "M15",
                    f"Low swept. 0.79 Fib @ {self.fib_level_price:.5f}",
                )
            return []

        # Step 3: M1 close beyond 0.79 confirms DOL direction.
        if not self.bias_confirmed:
            if self.sweep_side == "high" and m1.close < self.fib_level_price:
                self.bias_confirmed = True
                self.step_tracker.record(
                    "0.79 Fib Confirmed", 3, m1.time, m1.close, "M1",
                    "Bearish DOL toward session low.",
                )
            elif self.sweep_side == "low" and m1.close > self.fib_level_price:
                self.bias_confirmed = True
                self.step_tracker.record(
                    "0.79 Fib Confirmed", 3, m1.time, m1.close, "M1",
                    "Bullish DOL toward session high.",
                )
            else:
                return []

        # Step 4: find extreme FVG in dealing range for entry.
        m1_hist = history(self.symbol, TF.M1, 80)
        if len(m1_hist) < 5:
            return []

        fvgs = detect_fvg(m1_hist)
        direction = "bearish" if self.sweep_side == "high" else "bullish"
        candidates = [
            f for f in fvgs
            if f.direction == direction
            and f.low >= self.dealing_low
            and f.high <= self.dealing_high
        ]
        if not candidates:
            return []

        fvg = candidates[-1]
        entry = fvg.midpoint

        if direction == "bearish":
            sl = self.dealing_high
            risk = sl - entry
            if risk <= 0:
                return []
            tp = self.dol_target
            if tp >= entry:
                tp = entry - risk * 1.5
            self.trade_taken_today = True
            self.step_tracker.record(
                "FVG Entry", 4, m1.time, entry, "M1",
                f"Short at FVG midpoint {entry:.5f}",
            )
            return [Signal(
                strategy_id=self.id,
                direction=Direction.SHORT,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                timestamp=m1.time,
                symbol=self.symbol,
            )]

        sl = self.dealing_low
        risk = entry - sl
        if risk <= 0:
            return []
        tp = self.dol_target
        if tp <= entry:
            tp = entry + risk * 1.5
        self.trade_taken_today = True
        self.step_tracker.record(
            "FVG Entry", 4, m1.time, entry, "M1",
            f"Long at FVG midpoint {entry:.5f}",
        )
        return [Signal(
            strategy_id=self.id,
            direction=Direction.LONG,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            timestamp=m1.time,
            symbol=self.symbol,
        )]

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

        bar = bars.get(TF.M1)
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
