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
_LOADED = False
SKIP_DIRS = {"base", "registry", "__pycache__"}


def load_all_strategies(force: bool = False) -> dict[str, Type[BaseStrategy]]:
    """Import each strategy subfolder and register by Strategy.id."""
    global _LOADED
    if _LOADED and not force:
        return _REGISTRY

    strategies_dir = Path(__file__).resolve().parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in SKIP_DIRS:
            continue
        init_file = folder / "__init__.py"
        strategy_file = folder / "strategy.py"
        if not init_file.exists() or not strategy_file.exists():
            logger.warning("Skipping strategy folder missing required files: %s", folder.name)
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.error("Strategy folder %s does not export Strategy alias", folder.name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("Strategy in %s is not a BaseStrategy subclass", folder.name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("Strategy in %s has invalid id: %s", folder.name, strat_id)
                continue
            _REGISTRY[strat_id] = strategy_cls
        except Exception as exc:
            logger.exception("Error loading strategy module %s: %s", folder.name, exc)

    _LOADED = True
    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    return list(load_all_strategies().values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    if strategy_id in registry:
        return registry[strategy_id]
    for strat_id, strategy_cls in registry.items():
        module_name = strat_id.split("_", 1)[1] if "_" in strat_id else strat_id
        if strategy_id in {strat_id, module_name}:
            return strategy_cls
    return None


def list_strategy_metadata() -> list[dict[str, str]]:
    rows = []
    strategies_dir = Path(__file__).resolve().parent
    for strategy_cls in get_all_strategies():
        module_name = strategy_cls.__module__.split(".")[-2]
        if module_name == "strategies":
            module_name = strategy_cls.__module__.split(".")[-1]
        rows.append(
            {
                "id": strategy_cls.id,
                "name": strategy_cls.name,
                "module": module_name,
                "source_video": strategy_cls.source_video,
            }
        )
    return sorted(rows, key=lambda item: item["id"])
