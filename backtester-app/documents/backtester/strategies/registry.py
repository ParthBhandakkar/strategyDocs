"""
Strategy Registry — discovers strategies from subfolders.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Type

from .base import BaseStrategy

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Type[BaseStrategy]] = {}
_MODULE_BY_ID: dict[str, str] = {}

SKIP_DIRS = {"__pycache__", "base", "registry"}
SKIP_FILES = {"base.py", "registry.py", "__init__.py"}


def _strategies_root() -> Path:
    return Path(__file__).resolve().parent


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Import strategy folders and register Strategy classes by id."""
    global _REGISTRY, _MODULE_BY_ID
    if _REGISTRY:
        return _REGISTRY

    root = _strategies_root()

    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name in SKIP_DIRS:
            continue

        init_file = entry / "__init__.py"
        if not init_file.exists():
            continue

        module_name = f"backtester.strategies.{entry.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.warning("Folder %s missing Strategy export", entry.name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.warning("Folder %s Strategy is not a BaseStrategy subclass", entry.name)
                continue

            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.warning("Folder %s Strategy missing valid id", entry.name)
                continue

            _REGISTRY[strat_id] = strategy_cls
            _MODULE_BY_ID[strat_id] = entry.name
            logger.info("Registered strategy %s from %s", strat_id, entry.name)
        except Exception as exc:
            logger.error("Error loading strategy folder %s: %s", entry.name, exc)

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    """Return all registered strategy classes."""
    return list(load_all_strategies().values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    """Get a strategy class by registry id or module folder name."""
    registry = load_all_strategies()
    if strategy_id in registry:
        return registry[strategy_id]

    for strat_id, module_name in _MODULE_BY_ID.items():
        if module_name == strategy_id:
            return registry[strat_id]

    return None


def get_module_name(strategy_id: str) -> str | None:
    load_all_strategies()
    return _MODULE_BY_ID.get(strategy_id)
