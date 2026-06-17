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
_LOADED = False

SKIP_DIRS = {"__pycache__", "base", "registry", "tests"}


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Scan strategy subfolders and register Strategy classes by id."""
    global _LOADED
    if _LOADED:
        return _REGISTRY

    strategies_dir = Path(__file__).resolve().parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in SKIP_DIRS:
            continue
        init_file = folder / "__init__.py"
        if not init_file.exists():
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.error("Module %s missing Strategy export", module_name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("Module %s Strategy is not a BaseStrategy subclass", module_name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("Module %s has invalid strategy id", module_name)
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
    for sid, cls in registry.items():
        if sid.endswith(f"_{strategy_id}") or cls.__name__.lower() == strategy_id.lower():
            return cls
    folder_match = None
    for sid, cls in registry.items():
        module = sid.split("_", 1)[-1] if "_" in sid else sid
        if module == strategy_id:
            folder_match = cls
    return folder_match


def list_strategy_ids() -> list[str]:
    return sorted(load_all_strategies().keys())
