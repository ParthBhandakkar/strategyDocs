"""
Event-Driven Backtest Engine.
Main loop: dequeue events → dispatch to handlers → collect new events.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from . import BacktestConfig, BacktestResult, Signal
from .timeframes import TF
from .events import MarketEvent
from .data_feed import MultiTimeframeDataFeed
from .broker import SimulatedBroker
from .portfolio import Portfolio
from .step_tracker import StepTracker


class BacktestEngine:
    """
    Event-driven backtesting engine.
    
    Usage:
        engine = BacktestEngine(config, strategy, client)
        result = engine.run()
    """

    def __init__(
        self,
        config: BacktestConfig,
        strategy,  # BaseStrategy instance
        client,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ):
        self.config = config
        self.strategy = strategy
        self.client = client
        self.progress_callback = progress_callback

        # Initialize components
        self.broker = SimulatedBroker(
            spread_pips=config.spread_pips,
            slippage_pips=config.slippage_pips,
            commission_per_lot=config.commission_per_lot,
        )
        self.broker.set_pip_value(config.symbol)

        self.portfolio = Portfolio(config)
        self.step_tracker = StepTracker(strategy.id)

        # Build data feed with the strategy's required timeframes
        extra_symbols = []
        if hasattr(strategy, "extra_symbols"):
            extra_symbols = strategy.extra_symbols

        self.data_feed = MultiTimeframeDataFeed(
            client=client,
            symbol=config.symbol,
            timeframes=strategy.timeframes,
            start=config.start_date,
            end=config.end_date,
            extra_symbols=extra_symbols,
        )

    def run(self) -> BacktestResult:
        """Execute the backtest and return results."""
        print(f"\n{'='*60}")
        print(f"BACKTEST: {self.strategy.name}")
        print(f"Symbol: {self.config.symbol}")
        print(f"Period: {self.config.start_date.date()} → {self.config.end_date.date()}")
        print(f"Timeframes: {[tf.name for tf in self.strategy.timeframes]}")
        print(f"{'='*60}")

        # Load data
        print("\nLoading data...")
        self.data_feed.load()
        total_bars = self.data_feed.total_bars
        print(f"Total base bars: {total_bars}\n")

        if total_bars == 0:
            print("No data available!")
            return self.portfolio.get_result()

        # Initialize strategy
        self.strategy.initialize(
            symbol=self.config.symbol,
            broker=self.broker,
            step_tracker=self.step_tracker,
        )

        # Main loop
        bar_count = 0
        equity_interval = max(1, total_bars // 200)  # ~200 equity curve points

        for event in self.data_feed:
            bar_count += 1

            # 1. Let broker check SL/TP on open positions
            base_bar = event.bars.get(self.strategy.timeframes[0])
            if base_bar:
                closed_trades = self.broker.update_positions(base_bar, self.step_tracker)
                for trade in closed_trades:
                    self.portfolio.on_trade_closed(trade)

            # 2. Let strategy process the new bars
            signals = self.strategy.on_bar(
                bars=event.bars,
                history=self.data_feed.get_history,
                multi_symbol_bars=event.multi_symbol_bars,
                current_time=event.timestamp,
            )

            # 3. Execute any signals through the broker
            for signal in (signals or []):
                if not self.broker.has_open_position(signal.strategy_id):
                    fill = self.broker.execute_signal(
                        signal,
                        base_bar,
                        self.portfolio.balance,
                        self.config.risk_per_trade,
                    )
                    if fill:
                        # Assign pending steps to this trade
                        self.step_tracker.assign_to_trade(fill.trade_id)

                        # Record entry step
                        self.step_tracker.add_step_to_trade(
                            fill.trade_id,
                            "Trade Entry",
                            98,
                            event.timestamp,
                            fill.fill_price,
                            "",
                            f"{signal.direction.value} entry at {fill.fill_price:.5f}, "
                            f"SL: {signal.stop_loss:.5f}, TP: {signal.take_profit:.5f}",
                        )

            # 4. Let strategy manage open positions (e.g., move SL to BE)
            if self.broker.has_open_position(self.strategy.id):
                self.strategy.on_position_update(
                    bars=event.bars,
                    history=self.data_feed.get_history,
                    position=self.broker.get_open_position(self.strategy.id),
                    broker=self.broker,
                    step_tracker=self.step_tracker,
                    current_time=event.timestamp,
                )

            # 5. Record equity
            if bar_count % equity_interval == 0:
                self.portfolio.record_equity(event.timestamp)

            # 6. Progress callback
            if self.progress_callback and bar_count % 1000 == 0:
                self.progress_callback(bar_count, total_bars)

        # Force-close any remaining positions at the last bar
        last_bar = self.data_feed.get_current_bar()
        if last_bar:
            for pos in list(self.broker.open_positions):
                pos.trade.close(last_bar.time, last_bar.close, self.broker.pip_value)
                self.portfolio.on_trade_closed(pos.trade)
            self.broker.open_positions.clear()

        # Final equity point
        if self.data_feed.current_time:
            self.portfolio.record_equity(self.data_feed.current_time)

        # Compute results
        result = self.portfolio.get_result()

        print(f"\n{'='*60}")
        print(f"RESULTS")
        print(f"  Total Trades: {result.total_trades}")
        print(f"  Win Rate: {result.win_rate}%")
        print(f"  Profit Factor: {result.profit_factor}")
        print(f"  Max Drawdown: {result.max_drawdown_pct}%")
        print(f"  Total PnL: ${result.total_pnl:.2f}")
        print(f"  Avg R:R: {result.avg_rr}")
        print(f"{'='*60}\n")

        return result
