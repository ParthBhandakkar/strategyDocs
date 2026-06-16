"""
Strategy Registry — folder-based discovery of strategy modules.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Type

from .base import BaseStrategy

_REGISTRY: dict[str, Type[BaseStrategy]] = {}
_SKIP_DIRS = {"base", "registry", "__pycache__", "tests"}


def load_all_strategies() -> None:
    """Import Strategy from each subfolder under strategies/."""
    strategies_dir = Path(__file__).parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_DIRS:
            continue
        module_name = folder.name
        try:
            module = importlib.import_module(f"backtester.strategies.{module_name}")
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                print(f"Error loading strategy folder {module_name}: missing Strategy export")
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                print(f"Error loading strategy folder {module_name}: Strategy is not BaseStrategy")
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if strat_id and strat_id != "base_strategy":
                _REGISTRY[strat_id] = strategy_cls
        except Exception as exc:
            print(f"Error loading strategy folder {module_name}: {exc}")


def get_all_strategies() -> list[Type[BaseStrategy]]:
    if not _REGISTRY:
        load_all_strategies()
    return list(_REGISTRY.values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    if not _REGISTRY:
        load_all_strategies()
    if strategy_id in _REGISTRY:
        return _REGISTRY[strategy_id]
    for sid, cls in _REGISTRY.items():
        if sid.endswith(f"_{strategy_id}") or cls.__name__.lower() == strategy_id.lower():
            return cls
    return None


def list_strategy_ids() -> list[str]:
    if not _REGISTRY:
        load_all_strategies()
    return sorted(_REGISTRY.keys())
