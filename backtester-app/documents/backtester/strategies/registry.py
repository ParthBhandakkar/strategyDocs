"""
Folder-based strategy discovery.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Type

from .base import BaseStrategy

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Type[BaseStrategy]] = {}
_SKIP_DIRS = {"__pycache__", "base", "registry"}


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Discover strategy folders and register Strategy exports."""
    if _REGISTRY:
        return _REGISTRY

    strategies_dir = Path(__file__).resolve().parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_DIRS:
            continue
        init_file = folder / "__init__.py"
        if not init_file.exists():
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.error("Strategy folder %s missing Strategy export", folder.name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("Strategy export in %s is not a BaseStrategy subclass", folder.name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("Strategy folder %s has invalid id", folder.name)
                continue
            _REGISTRY[strat_id] = strategy_cls
        except Exception as exc:
            logger.error("Failed to import strategy folder %s: %s", folder.name, exc)
            print(f"Error loading strategy folder {folder.name}: {exc}")

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    return list(load_all_strategies().values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    if strategy_id in registry:
        return registry[strategy_id]
    for strat_id, strategy_cls in registry.items():
        if strategy_id in strat_id or strategy_id == strategy_cls.__module__.split(".")[-1]:
            return strategy_cls
    return None


def get_strategy_by_module(module_name: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    for strategy_cls in registry.values():
        module_suffix = strategy_cls.__module__.split(".")[-1]
        if module_suffix == module_name:
            return strategy_cls
    return None
