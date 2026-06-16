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
_MODULE_BY_ID: dict[str, str] = {}

SKIP_DIRS = {"base", "registry", "__pycache__", "tests"}


def load_all_strategies(force: bool = False) -> dict[str, Type[BaseStrategy]]:
    """Import each strategy subfolder and register its Strategy class."""
    if _REGISTRY and not force:
        return _REGISTRY

    strategies_dir = Path(__file__).resolve().parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in SKIP_DIRS:
            continue
        init_file = folder / "__init__.py"
        if not init_file.exists():
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            logger.error("Failed importing strategy folder %s: %s", folder.name, exc)
            print(f"[registry] Import error in {folder.name}: {exc}")
            continue

        strategy_cls = getattr(module, "Strategy", None)
        if strategy_cls is None:
            logger.error("Strategy folder %s missing Strategy export", folder.name)
            print(f"[registry] Missing Strategy export in {folder.name}")
            continue

        if not issubclass(strategy_cls, BaseStrategy):
            logger.error("Strategy in %s is not a BaseStrategy subclass", folder.name)
            print(f"[registry] Invalid Strategy class in {folder.name}")
            continue

        strat_id = getattr(strategy_cls, "id", None)
        if not strat_id or strat_id == "base_strategy":
            logger.error("Strategy in %s has invalid id", folder.name)
            print(f"[registry] Invalid strategy id in {folder.name}")
            continue

        _REGISTRY[strat_id] = strategy_cls
        _MODULE_BY_ID[strat_id] = folder.name

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    return list(load_all_strategies().values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    if strategy_id in registry:
        return registry[strategy_id]
    for sid, module_name in _MODULE_BY_ID.items():
        if module_name == strategy_id:
            return registry.get(sid)
    return None


def get_strategy_module(strategy_id: str) -> str | None:
    load_all_strategies()
    if strategy_id in _MODULE_BY_ID:
        return _MODULE_BY_ID[strategy_id]
    if strategy_id in _REGISTRY:
        return _MODULE_BY_ID.get(strategy_id)
    for sid, module_name in _MODULE_BY_ID.items():
        if module_name == strategy_id:
            return module_name
    return None
