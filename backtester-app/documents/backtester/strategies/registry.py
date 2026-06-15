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
_SKIP_DIRS = {"base", "registry", "__pycache__"}


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Discover strategies from subfolders exporting Strategy alias."""
    _REGISTRY.clear()
    strategies_dir = Path(__file__).parent

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
                logger.warning("Invalid strategy id in %s", module_name)
                continue
            _REGISTRY[strat_id] = strategy_cls
        except Exception as exc:
            logger.error("Error loading strategy module %s: %s", module_name, exc)

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    if not _REGISTRY:
        load_all_strategies()
    return list(_REGISTRY.values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    if not _REGISTRY:
        load_all_strategies()
    if strategy_id in _REGISTRY:
        return _REGISTRY[strategy_id]
    for folder, cls in _REGISTRY.items():
        if folder.endswith(strategy_id) or folder.split("_", 1)[-1] == strategy_id:
            return cls
    for folder, cls in _REGISTRY.items():
        module_suffix = folder.split("_", 1)[-1] if "_" in folder else folder
        if module_suffix == strategy_id:
            return cls
    return None


def get_registry() -> dict[str, Type[BaseStrategy]]:
    if not _REGISTRY:
        load_all_strategies()
    return dict(_REGISTRY)
