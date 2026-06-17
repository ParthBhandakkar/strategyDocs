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
_MODULE_INDEX: dict[str, str] = {}
_SKIP_DIRS = {"base", "registry", "__pycache__"}


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Discover strategies from subfolders exporting Strategy alias."""
    if _REGISTRY:
        return _REGISTRY

    strategies_dir = Path(__file__).parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_DIRS or folder.name.startswith("."):
            continue
        init_file = folder / "__init__.py"
        if not init_file.exists():
            logger.warning("Skipping %s: missing __init__.py", folder.name)
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.error("%s: no Strategy export in __init__.py", folder.name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("%s: Strategy is not a BaseStrategy subclass", folder.name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("%s: Strategy.id is missing or invalid", folder.name)
                continue
            _REGISTRY[strat_id] = strategy_cls
            _MODULE_INDEX[folder.name] = strat_id
            _MODULE_INDEX[strat_id] = strat_id
        except Exception as exc:
            logger.error("Failed to import strategy folder %s: %s", folder.name, exc)

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    return list(load_all_strategies().values())


def get_strategy(strategy_id_or_module: str) -> Type[BaseStrategy] | None:
    load_all_strategies()
    key = strategy_id_or_module.strip()
    if key in _REGISTRY:
        return _REGISTRY[key]
    if key in _MODULE_INDEX:
        return _REGISTRY.get(_MODULE_INDEX[key])
    return None


def get_registry_ids() -> list[str]:
    load_all_strategies()
    return sorted(_REGISTRY.keys())
