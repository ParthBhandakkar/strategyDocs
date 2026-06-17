"""
Folder-based strategy discovery.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Type

import yaml

from .base import BaseStrategy

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Type[BaseStrategy]] = {}
_MODULE_BY_ID: dict[str, str] = {}
_SKIP_DIRS = {"base", "registry", "__pycache__"}


def load_all_strategies(force: bool = False) -> dict[str, Type[BaseStrategy]]:
    if _REGISTRY and not force:
        return _REGISTRY

    if force:
        _REGISTRY.clear()
        _MODULE_BY_ID.clear()

    strategies_dir = Path(__file__).resolve().parent
    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in _SKIP_DIRS or folder.name.startswith("."):
            continue
        init_file = folder / "__init__.py"
        strategy_file = folder / "strategy.py"
        if not init_file.exists() or not strategy_file.exists():
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.error("Module %s missing Strategy export", module_name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("Module %s Strategy is not a BaseStrategy subclass", module_name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("Module %s Strategy missing valid id", module_name)
                continue
            _REGISTRY[strat_id] = strategy_cls
            _MODULE_BY_ID[strat_id] = folder.name
        except Exception as exc:
            logger.error("Error loading strategy folder %s: %s", folder.name, exc)

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    return list(load_all_strategies().values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    registry = load_all_strategies()
    if strategy_id in registry:
        return registry[strategy_id]
    for strat_id, module_name in _MODULE_BY_ID.items():
        if module_name == strategy_id:
            return registry.get(strat_id)
    return None


def get_strategy_module_name(strategy_id: str) -> str | None:
    load_all_strategies()
    return _MODULE_BY_ID.get(strategy_id)


def load_strategy_config(module_name: str) -> dict:
    config_path = Path(__file__).resolve().parent / module_name / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}
