"""
Strategy Registry — discovers strategies from subfolders.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Type

from .base import BaseStrategy

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Type[BaseStrategy]] = {}
_SKIP_FOLDERS = {"base", "registry", "__pycache__"}


def load_all_strategies() -> None:
    """Import Strategy from each subfolder under strategies/."""
    strategies_dir = Path(__file__).parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_FOLDERS:
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.warning("No Strategy export in %s", module_name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.warning("Strategy in %s is not a BaseStrategy subclass", module_name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.warning("Strategy in %s missing valid id", module_name)
                continue
            _REGISTRY[strat_id] = strategy_cls
        except Exception as exc:
            logger.error("Error loading strategy folder %s: %s", folder.name, exc)
            print(f"Error loading strategy folder {folder.name}: {exc}")


def get_all_strategies() -> list[Type[BaseStrategy]]:
    if not _REGISTRY:
        load_all_strategies()
    return list(_REGISTRY.values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    if not _REGISTRY:
        load_all_strategies()
    if strategy_id in _REGISTRY:
        return _REGISTRY[strategy_id]
    for strat_id, cls in _REGISTRY.items():
        folder = cls.__module__.rsplit(".", 1)[0].split(".")[-1]
        if strategy_id == folder:
            return cls
    return None


def get_strategy_by_module(module_name: str) -> Type[BaseStrategy] | None:
    if not _REGISTRY:
        load_all_strategies()
    for strat_id, cls in _REGISTRY.items():
        if cls.__module__.endswith(f".{module_name}"):
            return cls
    return None
