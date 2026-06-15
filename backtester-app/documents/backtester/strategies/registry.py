"""
Strategy Registry — folder-based discovery of strategy subpackages.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Type

import yaml

from .base import BaseStrategy

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[BaseStrategy]] = {}
_CONFIGS: dict[str, dict] = {}


def load_all_strategies(strategies_dir: Path | None = None) -> dict[str, type[BaseStrategy]]:
    """Discover strategies from subfolders exporting Strategy alias."""
    if strategies_dir is None:
        strategies_dir = Path(__file__).parent

    skip = {"base", "registry", "__pycache__"}

    for folder in sorted(strategies_dir.iterdir()):
        if not folder.is_dir() or folder.name in skip or folder.name.startswith("."):
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
                logger.error("Folder %s missing Strategy export in __init__.py", folder.name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("Folder %s Strategy is not a BaseStrategy subclass", folder.name)
                continue

            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("Folder %s Strategy missing valid id", folder.name)
                continue

            _REGISTRY[strat_id] = strategy_cls

            config_path = folder / "config.yaml"
            if config_path.exists():
                with open(config_path, encoding="utf-8") as f:
                    _CONFIGS[strat_id] = yaml.safe_load(f) or {}

            logger.info("Registered strategy %s from %s", strat_id, folder.name)
        except Exception as exc:
            logger.error("Failed to import strategy folder %s: %s", folder.name, exc)

    return _REGISTRY


def get_all_strategies() -> list[type[BaseStrategy]]:
    if not _REGISTRY:
        load_all_strategies()
    return list(_REGISTRY.values())


def get_strategy(strategy_id: str) -> type[BaseStrategy] | None:
    if not _REGISTRY:
        load_all_strategies()
    if strategy_id in _REGISTRY:
        return _REGISTRY[strategy_id]
    # Allow lookup by module folder name
    for sid, cls in _REGISTRY.items():
        if sid.endswith(f"_{strategy_id}") or cls.__module__.endswith(f".{strategy_id}"):
            return cls
    return None


def get_strategy_config(strategy_id: str) -> dict:
    if not _CONFIGS:
        load_all_strategies()
    return _CONFIGS.get(strategy_id, {})
