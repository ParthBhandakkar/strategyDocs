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
_LOAD_ERRORS: list[str] = []


def load_all_strategies(force: bool = False) -> dict[str, Type[BaseStrategy]]:
    """Discover strategies from subfolders exporting `Strategy`."""
    global _REGISTRY
    if _REGISTRY and not force:
        return _REGISTRY

    _REGISTRY = {}
    _LOAD_ERRORS.clear()

    strategies_dir = Path(__file__).resolve().parent
    skip = {"base", "registry", "__pycache__"}

    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in skip:
            continue
        init_file = folder / "__init__.py"
        if not init_file.exists():
            logger.warning("Skipping %s — missing __init__.py", folder.name)
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                msg = f"{module_name} does not export Strategy"
                _LOAD_ERRORS.append(msg)
                logger.error(msg)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                msg = f"{module_name}.Strategy is not a BaseStrategy subclass"
                _LOAD_ERRORS.append(msg)
                logger.error(msg)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                msg = f"{module_name}.Strategy missing valid id"
                _LOAD_ERRORS.append(msg)
                logger.error(msg)
                continue
            _REGISTRY[strat_id] = strategy_cls
        except Exception as exc:
            msg = f"Error loading strategy folder {folder.name}: {exc}"
            _LOAD_ERRORS.append(msg)
            logger.exception(msg)

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    return list(load_all_strategies().values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    if strategy_id in registry:
        return registry[strategy_id]
    for strat_id, cls in registry.items():
        if strategy_id == cls.__module__.split(".")[-1]:
            return cls
    return None


def get_load_errors() -> list[str]:
    load_all_strategies()
    return list(_LOAD_ERRORS)
