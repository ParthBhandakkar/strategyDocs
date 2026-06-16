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
_SKIP_DIRS = {"__pycache__", "tests"}
_SKIP_FILES = {"base", "registry"}


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Discover strategy folders and register Strategy classes by id."""
    if _REGISTRY:
        return _REGISTRY

    strategies_dir = Path(__file__).resolve().parent
    for entry in sorted(strategies_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in _SKIP_DIRS or entry.name.startswith("."):
            continue
        if not (entry / "__init__.py").exists() or not (entry / "strategy.py").exists():
            logger.warning("Skipping incomplete strategy folder: %s", entry.name)
            continue

        module_name = f"backtester.strategies.{entry.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.error("Folder %s missing Strategy export in __init__.py", entry.name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("Folder %s Strategy is not a BaseStrategy subclass", entry.name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("Folder %s Strategy missing valid id", entry.name)
                continue
            _REGISTRY[strat_id] = strategy_cls
            _REGISTRY[entry.name] = strategy_cls
        except Exception as exc:
            logger.error("Error loading strategy folder %s: %s", entry.name, exc)

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    """Return unique registered strategy classes."""
    registry = load_all_strategies()
    seen: set[str] = set()
    strategies: list[Type[BaseStrategy]] = []
    for key, cls in registry.items():
        if not key.startswith("s"):
            continue
        if cls.id in seen:
            continue
        seen.add(cls.id)
        strategies.append(cls)
    return sorted(strategies, key=lambda s: s.id)


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    """Get a strategy class by registry id or module folder name."""
    registry = load_all_strategies()
    return registry.get(strategy_id)


def list_strategy_entries() -> list[dict[str, str]]:
    """Return metadata for discovered strategies."""
    entries = []
    for cls in get_all_strategies():
        entries.append({
            "id": cls.id,
            "name": cls.name,
            "source_video": cls.source_video,
            "timeframes": ",".join(tf.name for tf in cls.timeframes),
        })
    return entries
