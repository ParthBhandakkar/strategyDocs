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
_SKIP_DIRS = {"base", "registry", "__pycache__"}


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Discover strategy folders and register Strategy classes by id."""
    if _REGISTRY:
        return _REGISTRY

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
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.error("Strategy folder %s does not export Strategy alias", folder.name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("%s.Strategy is not a BaseStrategy subclass", folder.name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("%s has invalid strategy id", folder.name)
                continue
            _REGISTRY[strat_id] = strategy_cls
            module_id = getattr(strategy_cls, "module", folder.name)
            _REGISTRY.setdefault(module_id, strategy_cls)
        except Exception as exc:
            logger.error("Error loading strategy folder %s: %s", folder.name, exc)
    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    registry = load_all_strategies()
    seen: set[str] = set()
    unique: list[Type[BaseStrategy]] = []
    for key, cls in registry.items():
        if cls.id in seen:
            continue
        seen.add(cls.id)
        unique.append(cls)
    return unique


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    return registry.get(strategy_id)


def list_strategy_entries() -> list[dict[str, str]]:
    entries = []
    for cls in get_all_strategies():
        entries.append(
            {
                "id": cls.id,
                "name": cls.name,
                "module": getattr(cls, "module", cls.id.split("_", 1)[-1]),
                "source_video": cls.source_video,
            }
        )
    return sorted(entries, key=lambda item: item["id"])
