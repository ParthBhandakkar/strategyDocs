"""
Session boundaries using America/New_York timezone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from backtester.core import Bar

NY_TZ = ZoneInfo("America/New_York")


@dataclass
class SessionRange:
    name: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    high: float = 0.0
    low: float = float("inf")
    open_price: float = 0.0
    close_price: float = 0.0


SESSIONS = {
    "asia": {"start": time(20, 0), "end": time(0, 0), "cross": True},
    "london": {"start": time(3, 0), "end": time(12, 0), "cross": False},
    "new_york": {"start": time(9, 30), "end": time(16, 0), "cross": False},
    "london_killzone": {"start": time(3, 0), "end": time(5, 0), "cross": False},
    "ny_killzone": {"start": time(7, 0), "end": time(11, 0), "cross": False},
    "ny_am": {"start": time(9, 30), "end": time(12, 0), "cross": False},
    "ny_pm": {"start": time(12, 0), "end": time(14, 0), "cross": False},
}

RESTRICTED_HOURS = {
    "ny_lunch": {"start": time(12, 0), "end": time(13, 30)},
}


def get_ny_time(utc_time: datetime) -> datetime:
    """Convert naive UTC bar time to New York local time."""
    if utc_time.tzinfo is None:
        aware = utc_time.replace(tzinfo=ZoneInfo("UTC"))
    else:
        aware = utc_time
    return aware.astimezone(NY_TZ).replace(tzinfo=None)


def is_restricted_hour(utc_time: datetime) -> bool:
    ny = get_ny_time(utc_time)
    for _, restricted in RESTRICTED_HOURS.items():
        if restricted["start"] <= ny.time() <= restricted["end"]:
            return True
    return False


def is_in_session(utc_time: datetime, session_name: str) -> bool:
    ny = get_ny_time(utc_time)
    session = SESSIONS.get(session_name)
    if not session:
        return False
    if session.get("cross"):
        return ny.time() >= session["start"] or ny.time() <= session["end"]
    return session["start"] <= ny.time() <= session["end"]


def is_in_killzone(utc_time: datetime, kz: str = "ny_killzone") -> bool:
    return is_in_session(utc_time, kz)


def get_candle_at_time(bars: list[Bar], hour: int, minute: int = 0) -> Optional[Bar]:
    for bar in reversed(bars):
        bar_time = get_ny_time(bar.time)
        if bar_time.hour == hour and bar_time.minute == minute:
            return bar
    return None


def get_session_range(bars: list[Bar], session_name: str) -> Optional[SessionRange]:
    session_bars = [b for b in bars if is_in_session(b.time, session_name)]
    if not session_bars:
        return None
    session_range = SessionRange(
        name=session_name,
        start_time=session_bars[0].time,
        end_time=session_bars[-1].time,
        open_price=session_bars[0].open,
        close_price=session_bars[-1].close,
    )
    session_range.high = max(b.high for b in session_bars)
    session_range.low = min(b.low for b in session_bars)
    return session_range


def get_previous_day_high_low(bars: list[Bar], utc_time: datetime) -> tuple[float, float]:
    target: date = get_ny_time(utc_time).date() - timedelta(days=1)
    day_bars = [b for b in bars if get_ny_time(b.time).date() == target]
    if not day_bars:
        return 0.0, 0.0
    return max(b.high for b in day_bars), min(b.low for b in day_bars)


def session_bars_since_ny_open(bars: list[Bar], current_time: datetime) -> list[Bar]:
    """Bars from 09:30 NY on the current session day up to current_time."""
    ny_now = get_ny_time(current_time)
    session_day = ny_now.date()
    if ny_now.time() < time(9, 30):
        return []
    result: list[Bar] = []
    for bar in bars:
        ny_bar = get_ny_time(bar.time)
        if ny_bar.date() != session_day:
            continue
        if ny_bar.time() < time(9, 30):
            continue
        if bar.time > current_time:
            break
        result.append(bar)
    return result
