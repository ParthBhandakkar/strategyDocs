"""Symbol-aware pip, contract, and dollar-per-pip specifications."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolSpec:
    pip_value: float
    contract_size: float
    dollar_per_pip_per_lot: float


def get_symbol_spec(symbol: str) -> SymbolSpec:
    sym = symbol.upper()

    if sym in ("BTCUSD", "ETHUSD"):
        return SymbolSpec(pip_value=1.0, contract_size=1.0, dollar_per_pip_per_lot=1.0)
    if "XAU" in sym or sym == "GOLD":
        return SymbolSpec(pip_value=0.1, contract_size=100.0, dollar_per_pip_per_lot=10.0)
    if "XAG" in sym or sym == "SILVER":
        return SymbolSpec(pip_value=0.01, contract_size=5000.0, dollar_per_pip_per_lot=50.0)
    if "JPY" in sym:
        return SymbolSpec(pip_value=0.01, contract_size=100_000.0, dollar_per_pip_per_lot=6.5)

    return SymbolSpec(pip_value=0.0001, contract_size=100_000.0, dollar_per_pip_per_lot=10.0)
