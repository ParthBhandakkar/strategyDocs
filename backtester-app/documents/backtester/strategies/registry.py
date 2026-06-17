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
_SKIP_DIRS = {"base", "registry", "__pycache__"}


def load_all_strategies() -> None:
    """Import each strategy folder and register its Strategy class by id."""
    strategies_dir = Path(__file__).parent
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
        except Exception as exc:
            logger.error("Failed importing strategy folder %s: %s", folder.name, exc)
            continue

        strategy_cls = getattr(module, "Strategy", None)
        if strategy_cls is None:
            logger.error("Strategy folder %s does not export Strategy alias", folder.name)
            continue
        if not issubclass(strategy_cls, BaseStrategy):
            logger.error("Strategy in %s is not a BaseStrategy subclass", folder.name)
            continue

        strat_id = getattr(strategy_cls, "id", None)
        if not strat_id or strat_id == "base_strategy":
            logger.error("Strategy folder %s has invalid id", folder.name)
            continue
        _REGISTRY[strat_id] = strategy_cls


def get_all_strategies() -> list[Type[BaseStrategy]]:
    if not _REGISTRY:
        load_all_strategies()
    return list(_REGISTRY.values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    if not _REGISTRY:
        load_all_strategies()
    if strategy_id in _REGISTRY:
        return _REGISTRY[strategy_id]
    for strat_id, strategy_cls in _REGISTRY.items():
        if strategy_id == strategy_cls.__module__.split(".")[-1]:
            return strategy_cls
    return None


def list_strategy_ids() -> list[str]:
    if not _REGISTRY:
        load_all_strategies()
    return sorted(_REGISTRY.keys())
