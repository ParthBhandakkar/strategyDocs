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
_SKIP_DIRS = {"base", "registry", "__pycache__"}


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Discover strategy folders and register Strategy classes by id."""
    if _REGISTRY:
        return _REGISTRY

    strategies_dir = Path(__file__).resolve().parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_DIRS or folder.name.startswith("."):
            continue
        init_file = folder / "__init__.py"
        if not init_file.exists():
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
            logger.error("Failed to import strategy folder %s: %s", folder.name, exc)

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    return list(load_all_strategies().values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    if strategy_id in registry:
        return registry[strategy_id]
    for strat_id, cls in registry.items():
        if strategy_id in strat_id or strat_id.endswith(strategy_id):
            return cls
    module_match = {cls.__module__.split(".")[-1]: cls for cls in registry.values()}
    return module_match.get(strategy_id)


def list_strategy_ids() -> list[str]:
    return sorted(load_all_strategies().keys())
