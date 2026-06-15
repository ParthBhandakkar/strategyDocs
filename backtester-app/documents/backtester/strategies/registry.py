"""
Strategy Registry — discovers strategy folders and registers Strategy classes.
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


def load_all_strategies(force: bool = False) -> dict[str, Type[BaseStrategy]]:
    """Import each strategy subfolder and register its Strategy class."""
    if _REGISTRY and not force:
        return _REGISTRY

    if force:
        _REGISTRY.clear()

    strategies_dir = Path(__file__).resolve().parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_DIRS:
            continue
        init_file = folder / "__init__.py"
        strategy_file = folder / "strategy.py"
        if not init_file.exists() or not strategy_file.exists():
            logger.warning("Skipping strategy folder missing contract files: %s", folder.name)
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.error("Strategy folder %s missing Strategy export", folder.name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("Strategy export in %s is not a BaseStrategy subclass", folder.name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("Strategy class in %s missing valid id", folder.name)
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
    for folder_id, strategy_cls in registry.items():
        if folder_id.endswith(f"_{strategy_id}") or strategy_cls.__name__.lower() == strategy_id.lower():
            return strategy_cls
    for folder_id, strategy_cls in registry.items():
        module_suffix = folder_id.split("_", 1)[-1] if "_" in folder_id else folder_id
        if module_suffix == strategy_id:
            return strategy_cls
    return None


def list_strategy_metadata() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for strategy_cls in get_all_strategies():
        rows.append(
            {
                "id": strategy_cls.id,
                "name": strategy_cls.name,
                "source_video": strategy_cls.source_video,
                "module": strategy_cls.__module__.rsplit(".", 2)[-2],
            }
        )
    return sorted(rows, key=lambda row: row["id"])
