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
_SKIP_DIRS = {"base", "registry", "__pycache__", "tests"}


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Import each strategy subfolder and register its Strategy class."""
    if _REGISTRY:
        return _REGISTRY

    strategies_dir = Path(__file__).parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_DIRS:
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.warning("No Strategy export in %s", module_name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.warning("%s.Strategy is not a BaseStrategy subclass", module_name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.warning("Strategy in %s missing valid id", module_name)
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
        if strat_id.endswith(f"_{strategy_id}") or cls.__name__.lower() == strategy_id.lower():
            return cls
    folder_match = load_all_strategies()
    for strat_id, cls in folder_match.items():
        module_suffix = strat_id.split("_", 1)[-1] if "_" in strat_id else strat_id
        if module_suffix == strategy_id:
            return cls
    return None


def list_strategy_ids() -> list[str]:
    return sorted(load_all_strategies().keys())
