"""Symbol contract and pip specifications for consistent USD PnL."""

from __future__ import annotations


def pip_size(symbol: str) -> float:
    sym = symbol.upper()
    if "JPY" in sym:
        return 0.01
    if "XAU" in sym or "GOLD" in sym:
        return 0.1
    if "XAG" in sym or "SILVER" in sym:
        return 0.01
    if sym in {"BTCUSD", "ETHUSD"}:
        return 1.0
    return 0.0001


def contract_size(symbol: str) -> float:
    sym = symbol.upper()
    if "XAU" in sym or "GOLD" in sym:
        return 100.0
    if "XAG" in sym or "SILVER" in sym:
        return 5000.0
    if sym in {"BTCUSD", "ETHUSD"}:
        return 1.0
    return 100_000.0


def usd_per_price_unit(symbol: str, price: float, lot_size: float) -> float:
    """USD PnL multiplier for a 1.0 price-unit move at given lot size."""
    return contract_size(symbol) * lot_size


def usd_pnl(
    symbol: str,
    direction_sign: int,
    entry_price: float,
    exit_price: float,
    lot_size: float,
    commission: float = 0.0,
) -> float:
    """
    Compute USD PnL from price move.
    direction_sign: +1 long, -1 short (applied via price delta).
    """
    price_delta = (exit_price - entry_price) if direction_sign > 0 else (entry_price - exit_price)
    gross = price_delta * usd_per_price_unit(symbol, entry_price, lot_size)
    return round(gross - commission, 2)
