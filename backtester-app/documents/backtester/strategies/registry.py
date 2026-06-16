"""
Strategy Registry — folder-based discovery of strategy subpackages.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Type

from .base import BaseStrategy

logger = logging.getLogger(__name__)
_REGISTRY: dict[str, Type[BaseStrategy]] = {}
_SKIP_DIRS = {"__pycache__", "tests"}


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Scan strategy subfolders and register Strategy classes by id."""
    if _REGISTRY:
        return _REGISTRY

    strategies_dir = Path(__file__).parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_DIRS:
            continue
        if folder.name in ("base", "registry"):
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
            logger.error("Failed importing strategy folder %s: %s", folder.name, exc)
            raise

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
        module = cls.__module__.split(".")[-1]
        if module == strategy_id:
            folder_match = cls
            break
    return folder_match


def get_strategy_by_module(module_name: str) -> Type[BaseStrategy] | None:
    for cls in get_all_strategies():
        if cls.__module__.endswith(f".{module_name}"):
            return cls
    return None
