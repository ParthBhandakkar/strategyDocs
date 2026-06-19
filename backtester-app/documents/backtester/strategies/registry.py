"""
Strategy Registry — Automatically discovers and registers all strategies in this directory.
"""

import importlib
import inspect
import pkgutil
from typing import Type

from .base import BaseStrategy

_REGISTRY: dict[str, Type[BaseStrategy]] = {}


def load_all_strategies():
    """Dynamically import all modules in this package and register subclasses of BaseStrategy."""
    import backtester.strategies as strats_pkg
    
    for _, module_name, _ in pkgutil.iter_modules(strats_pkg.__path__):
        if module_name in ["base", "registry"]:
            continue
            
        try:
            # Import the module
            module = importlib.import_module(f"backtester.strategies.{module_name}")
            
            # Find all classes that inherit from BaseStrategy (but are not BaseStrategy itself)
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
                    # Instantiate briefly to get the ID, or assume it's set on the class
                    strat_id = getattr(obj, "id", None)
                    if strat_id and strat_id != "base_strategy":
                        _REGISTRY[strat_id] = obj
        except Exception as e:
            print(f"Error loading strategy module {module_name}: {e}")


def get_all_strategies() -> list[Type[BaseStrategy]]:
    """Return all registered strategy classes."""
    if not _REGISTRY:
        load_all_strategies()
    return list(_REGISTRY.values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    """Get a strategy class by ID."""
    if not _REGISTRY:
        load_all_strategies()
    return _REGISTRY.get(strategy_id)


STRATEGY_REGISTRY = _REGISTRY
