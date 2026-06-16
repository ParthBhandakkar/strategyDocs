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
_SKIP_DIRS = {"base", "registry", "__pycache__", "tests"}


def _strategies_root() -> Path:
    return Path(__file__).resolve().parent


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Import Strategy from each subfolder under strategies/."""
    global _REGISTRY
    if _REGISTRY:
        return _REGISTRY

    root = _strategies_root()
    for folder in sorted(root.iterdir()):
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
        except Exception as exc:
            logger.error("Error loading strategy folder %s: %s", folder.name, exc)
    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    return list(load_all_strategies().values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    if strategy_id in registry:
        return registry[strategy_id]
    for strat_id, cls in registry.items():
        if strat_id.endswith(f"_{strategy_id}") or cls.__name__.lower() == strategy_id.lower():
            return cls
    folder_match = strategy_id.replace("s", "s", 1)
    for strat_id, cls in registry.items():
        module = strat_id.split("_", 1)[-1] if "_" in strat_id else strat_id
        if module == strategy_id:
            return cls
    return None


def list_strategy_ids() -> list[str]:
    return sorted(load_all_strategies().keys())
