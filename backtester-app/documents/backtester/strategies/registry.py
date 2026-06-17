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


def load_all_strategies() -> None:
    """Import each strategy subfolder and register its Strategy class."""
    strategies_dir = Path(__file__).resolve().parent
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
                logger.error("Module %s does not export Strategy alias", module_name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("%s.Strategy is not a BaseStrategy subclass", module_name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("%s.Strategy missing valid id", module_name)
                continue
            _REGISTRY[strat_id] = strategy_cls
            _REGISTRY[folder.name] = strategy_cls
        except Exception as exc:
            logger.error("Failed to import strategy folder %s: %s", folder.name, exc)


def get_all_strategies() -> list[Type[BaseStrategy]]:
    if not _REGISTRY:
        load_all_strategies()
    seen: set[str] = set()
    unique: list[Type[BaseStrategy]] = []
    for key, cls in _REGISTRY.items():
        if cls.id in seen:
            continue
        seen.add(cls.id)
        unique.append(cls)
    return unique


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    if not _REGISTRY:
        load_all_strategies()
    return _REGISTRY.get(strategy_id)


def list_strategy_entries() -> list[dict[str, str]]:
    if not _REGISTRY:
        load_all_strategies()
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for cls in get_all_strategies():
        if cls.id in seen:
            continue
        seen.add(cls.id)
        entries.append(
            {
                "id": cls.id,
                "name": cls.name,
                "module": cls.id.split("_", 1)[-1] if "_" in cls.id else cls.id,
                "source_video": cls.source_video,
            }
        )
    return sorted(entries, key=lambda item: item["id"])
