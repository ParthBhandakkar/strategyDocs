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


def _strategies_dir() -> Path:
    return Path(__file__).resolve().parent


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Discover strategy folders and register Strategy classes by id."""
    if _REGISTRY:
        return _REGISTRY

    root = _strategies_dir()
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_DIRS:
            continue
        init_file = folder / "__init__.py"
        if not init_file.exists():
            logger.warning("Skipping %s: missing __init__.py", folder.name)
            continue
        module_path = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_path)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.error(
                    "Strategy folder %s must export `Strategy` from __init__.py",
                    folder.name,
                )
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("%s.Strategy is not a BaseStrategy subclass", module_path)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("%s.Strategy missing valid id", module_path)
                continue
            _REGISTRY[strat_id] = strategy_cls
            module_id = getattr(strategy_cls, "module_id", folder.name)
            _REGISTRY.setdefault(module_id, strategy_cls)
        except Exception as exc:
            logger.error("Failed importing strategy folder %s: %s", folder.name, exc)

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    """Return unique registered strategy classes."""
    registry = load_all_strategies()
    seen: set[str] = set()
    result: list[Type[BaseStrategy]] = []
    for key, cls in registry.items():
        if cls.id in seen:
            continue
        seen.add(cls.id)
        result.append(cls)
    return sorted(result, key=lambda c: c.id)


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    """Get a strategy class by registry id or module folder name."""
    registry = load_all_strategies()
    return registry.get(strategy_id)
