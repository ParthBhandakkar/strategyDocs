"""
Strategy Registry — folder-based discovery of strategy modules.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Type

from .base import BaseStrategy

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Type[BaseStrategy]] = {}

SKIP_FOLDERS = {"base", "registry", "__pycache__"}


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Import Strategy from each subfolder under strategies/."""
    if _REGISTRY:
        return _REGISTRY

    strategies_dir = Path(__file__).resolve().parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in SKIP_FOLDERS:
            continue
        init_file = folder / "__init__.py"
        strategy_file = folder / "strategy.py"
        if not init_file.exists() or not strategy_file.exists():
            logger.warning("Skipping incomplete strategy folder: %s", folder.name)
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.error("Folder %s missing Strategy export", folder.name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("Folder %s Strategy is not a BaseStrategy subclass", folder.name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("Folder %s Strategy missing valid id", folder.name)
                continue
            _REGISTRY[strat_id] = strategy_cls
        except Exception as exc:
            logger.error("Error loading strategy folder %s: %s", folder.name, exc)

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    return list(load_all_strategies().values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    if strategy_id in registry:
        return registry[strategy_id]
    for strat_id, cls in registry.items():
        if strategy_id in strat_id or strat_id.endswith(f"_{strategy_id}"):
            return cls
    for strat_id, cls in registry.items():
        if cls.__module__.endswith(f".{strategy_id}"):
            return cls
    return None


def get_strategy_by_module(module_name: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    for strat_id, cls in registry.items():
        if strat_id.endswith(f"_{module_name}") or cls.__module__.endswith(f".{module_name}"):
            return cls
    return None
