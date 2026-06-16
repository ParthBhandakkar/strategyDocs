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
_LOADED = False

SKIP_DIRS = {"base", "registry", "__pycache__"}


def load_all_strategies(force: bool = False) -> dict[str, Type[BaseStrategy]]:
    global _LOADED
    if _LOADED and not force:
        return _REGISTRY

    _REGISTRY.clear()
    strategies_dir = Path(__file__).resolve().parent

    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in SKIP_DIRS:
            continue
        init_file = folder / "__init__.py"
        if not init_file.exists():
            logger.warning("Skipping strategy folder without __init__.py: %s", folder.name)
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.error("Module %s does not export Strategy alias", module_name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("Strategy in %s is not a BaseStrategy subclass", module_name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("Strategy in %s missing valid id", module_name)
                continue
            _REGISTRY[strat_id] = strategy_cls
        except Exception as exc:
            logger.error("Failed importing strategy folder %s: %s", folder.name, exc)

    _LOADED = True
    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    return list(load_all_strategies().values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    if strategy_id in registry:
        return registry[strategy_id]
    for strat_id, strategy_cls in registry.items():
        if strategy_id == strategy_cls.__module__.split(".")[-1]:
            return strategy_cls
    return None
