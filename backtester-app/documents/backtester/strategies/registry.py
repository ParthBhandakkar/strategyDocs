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
_SKIP_DIRS = {"base", "registry", "__pycache__"}


def _strategies_root() -> Path:
    return Path(__file__).resolve().parent


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Discover strategies from subfolders exporting `Strategy`."""
    if _REGISTRY:
        return _REGISTRY

    root = _strategies_root()
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_DIRS:
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
                logger.warning("%s.Strategy is not a BaseStrategy subclass", module_name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.warning("Invalid strategy id in %s", module_name)
                continue
            _REGISTRY[strat_id] = strategy_cls
        except Exception as exc:
            logger.error("Failed to import strategy folder %s: %s", folder.name, exc)
            raise

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    return list(load_all_strategies().values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    return load_all_strategies().get(strategy_id)


def get_strategy_by_module(module_name: str) -> Type[BaseStrategy] | None:
    for cls in get_all_strategies():
        if cls.id.endswith(f"_{module_name}") or cls.__module__.endswith(f".{module_name}"):
            return cls
    return None


def list_strategy_ids() -> list[str]:
    return sorted(load_all_strategies().keys())
