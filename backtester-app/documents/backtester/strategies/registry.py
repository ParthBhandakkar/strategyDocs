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


def load_all_strategies() -> None:
    """Import Strategy alias from each subfolder under strategies/."""
    strategies_dir = Path(__file__).resolve().parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_DIRS:
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
                logger.error("Module %s does not export Strategy", module_name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("%s.Strategy is not a BaseStrategy subclass", module_name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("%s.Strategy missing valid id", module_name)
                continue
            _REGISTRY[strat_id] = strategy_cls
            logger.info("Registered strategy %s from %s", strat_id, folder.name)
        except Exception as exc:
            logger.exception("Failed to load strategy folder %s: %s", folder.name, exc)


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
        if strategy_id == cls.__module__.split(".")[-1]:
            return cls
    return None


def list_strategy_ids() -> list[str]:
    if not _REGISTRY:
        load_all_strategies()
    return sorted(_REGISTRY.keys())
