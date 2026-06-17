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
_SKIP_DIRS = {"__pycache__", "base", "registry", "tests"}


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Discover strategy folders and register Strategy classes by id."""
    if _REGISTRY:
        return _REGISTRY

    strategies_dir = Path(__file__).resolve().parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_DIRS:
            continue
        init_file = folder / "__init__.py"
        strategy_file = folder / "strategy.py"
        if not init_file.exists() or not strategy_file.exists():
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
                logger.error("Module %s Strategy missing valid id", module_name)
                continue
            _REGISTRY[strat_id] = strategy_cls
            _REGISTRY[folder.name] = strategy_cls
        except Exception as exc:
            logger.error("Error loading strategy module %s: %s", module_name, exc)
    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    registry = load_all_strategies()
    seen: set[str] = set()
    unique: list[Type[BaseStrategy]] = []
    for key, strategy_cls in registry.items():
        strat_id = strategy_cls.id
        if strat_id in seen:
            continue
        seen.add(strat_id)
        unique.append(strategy_cls)
    return unique


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    return registry.get(strategy_id)
