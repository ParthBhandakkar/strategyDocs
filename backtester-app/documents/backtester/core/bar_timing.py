"""
Bar timing helpers — ensure strategies only act on fully closed candles.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from backtester.core import Bar
from backtester.core.timeframes import TF, tf_to_minutes


def bar_close_time(bar: Bar, tf: TF) -> datetime:
    """Return the UTC timestamp when a bar's period ends (exclusive open, inclusive close)."""
    return bar.time + timedelta(minutes=tf_to_minutes(tf))


def is_bar_closed(bar: Bar, tf: TF, as_of: datetime) -> bool:
    """True when the full OHLC of `bar` would be known at `as_of`."""
    return bar_close_time(bar, tf) <= as_of
