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
_SKIP_FOLDERS = {"base", "registry", "__pycache__"}


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Discover strategies from subfolders exporting `Strategy`."""
    if _REGISTRY:
        return _REGISTRY

    strategies_dir = Path(__file__).parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_FOLDERS or folder.name.startswith("."):
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
                logger.error("Module %s does not export Strategy alias", module_name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("%s.Strategy is not a BaseStrategy subclass", module_name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("%s has invalid strategy id", module_name)
                continue
            _REGISTRY[strat_id] = strategy_cls
            module_id = getattr(strategy_cls, "id", folder.name)
            logger.info("Registered strategy %s from %s", module_id, folder.name)
        except Exception as exc:
            logger.error("Failed importing strategy folder %s: %s", folder.name, exc)
    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    """Return all registered strategy classes."""
    return list(load_all_strategies().values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    """Get a strategy class by registry ID or module folder name."""
    registry = load_all_strategies()
    if strategy_id in registry:
        return registry[strategy_id]
    for strat_id, cls in registry.items():
        if strategy_id in strat_id or strat_id.endswith(f"_{strategy_id}"):
            return cls
    return None


def get_strategy_by_module(module_name: str) -> Type[BaseStrategy] | None:
    """Resolve strategy by folder module name."""
    return get_strategy(module_name)
