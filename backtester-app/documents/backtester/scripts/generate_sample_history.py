#!/usr/bin/env python3
"""Generate minimal Exness-format OHLCV history for pipeline smoke tests."""

from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

SYMBOLS = [
    "AUDCHF", "AUDUSD", "BTCUSD", "CADCHF", "CADJPY", "CHFJPY", "ETHUSD",
    "EURCHF", "EURGBP", "EURUSD", "GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY",
    "GBPNZD", "GBPUSD", "NZDJPY", "NZDUSD", "USDCAD", "USDCHF", "USDJPY",
    "XAUUSD",
]

BASE_PRICES = {
    "EURUSD": 1.0850,
    "GBPUSD": 1.2650,
    "USDJPY": 150.50,
    "XAUUSD": 2350.0,
    "BTCUSD": 65000.0,
    "ETHUSD": 3500.0,
    "AUDUSD": 0.6550,
    "USDCAD": 1.3550,
    "USDCHF": 0.8850,
    "NZDUSD": 0.6050,
    "EURGBP": 0.8580,
    "EURJPY": 163.0,
    "GBPJPY": 190.0,
    "AUDJPY": 98.5,
    "EURCHF": 0.9600,
    "GBPCHF": 1.1200,
    "CADCHF": 0.6530,
    "AUDCHF": 0.5800,
    "CADJPY": 111.0,
    "CHFJPY": 170.0,
    "NZDJPY": 91.0,
    "GBPAUD": 1.9300,
    "GBPCAD": 1.7150,
    "GBPNZD": 2.0900,
    "EURCAD": 1.4700,
    "EURNZD": 1.7900,
}


def base_price(symbol: str) -> float:
    return BASE_PRICES.get(symbol, 1.1000)


def pip_size(symbol: str) -> float:
    if "JPY" in symbol:
        return 0.01
    if symbol in ("XAUUSD",):
        return 0.1
    if symbol in ("BTCUSD",):
        return 1.0
    if symbol in ("ETHUSD",):
        return 0.1
    return 0.0001


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "time_utc", "Day_IST", "Time_IST", "time", "open", "high", "low", "close",
        "tick_volume", "spread", "real_volume",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def generate_m1_bars(symbol: str, start: datetime, days: int = 10) -> list[dict]:
    price = base_price(symbol)
    pip = pip_size(symbol)
    rows = []
    t = start
    end = start + timedelta(days=days)

    i = 0
    while t < end:
        ny_hour = (t.hour - 5) % 24
        session_boost = 1.0
        if 14 <= t.hour <= 21:
            session_boost = 2.5

        drift = math.sin(i / 37.0) * 8 * pip
        o = price + drift
        upper_wick = pip * (4 if (i % 47 == 0 and 14 <= t.hour <= 20) else 1)
        lower_wick = pip * (4 if (i % 53 == 0 and 14 <= t.hour <= 20) else 1)

        if i % 47 == 0 and 14 <= t.hour <= 20:
            c = o - pip * 2
        elif i % 53 == 0 and 14 <= t.hour <= 20:
            c = o + pip * 2
        else:
            c = o + math.sin(i / 11.0) * 3 * pip

        h = max(o, c) + upper_wick
        l = min(o, c) - lower_wick

        vol = int(120 * session_boost)
        if upper_wick > pip * 2:
            vol = int(vol * 3.0)
        if lower_wick > pip * 2:
            vol = int(vol * 3.0)

        rows.append({
            "time_utc": t.isoformat(),
            "Day_IST": t.strftime("%Y-%m-%d"),
            "Time_IST": t.strftime("%H:%M:%S"),
            "time": t.isoformat(),
            "open": round(o, 5),
            "high": round(h, 5),
            "low": round(l, 5),
            "close": round(c, 5),
            "tick_volume": vol,
            "spread": 10,
            "real_volume": 0,
        })

        price = c
        t += timedelta(minutes=1)
        i += 1

    return rows


def generate_d1_bars(symbol: str, start: datetime, days: int = 30) -> list[dict]:
    price = base_price(symbol)
    pip = pip_size(symbol)
    rows = []
    t = start.replace(hour=0, minute=0, second=0, microsecond=0)

    for day in range(days):
        o = price
        c = o + math.sin(day / 5.0) * 20 * pip
        h = max(o, c) + 15 * pip
        l = min(o, c) - 15 * pip
        bar_time = t + timedelta(days=day)
        rows.append({
            "time_utc": bar_time.isoformat(),
            "Day_IST": bar_time.strftime("%Y-%m-%d"),
            "Time_IST": "00:00:00",
            "time": bar_time.isoformat(),
            "open": round(o, 5),
            "high": round(h, 5),
            "low": round(l, 5),
            "close": round(c, 5),
            "tick_volume": 50000,
            "spread": 10,
            "real_volume": 0,
        })
        price = c

    return rows


def main():
    root = Path("/workspace/data/exness/structured/history")
    start = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
    end = start + timedelta(days=10)

    for symbol in SYMBOLS:
        m1_rows = generate_m1_bars(symbol, start, days=10)
        d1_rows = generate_d1_bars(symbol, start - timedelta(days=30), days=40)

        m1_name = f"{symbol}_1m_{start.date()}_{end.date()}.csv"
        d1_name = f"{symbol}_1d_{(start - timedelta(days=30)).date()}_{end.date()}.csv"

        write_csv(root / symbol / "1m" / m1_name, m1_rows)
        write_csv(root / symbol / "1d" / d1_name, d1_rows)

    print(f"Generated history for {len(SYMBOLS)} symbols at {root}")


if __name__ == "__main__":
    main()
