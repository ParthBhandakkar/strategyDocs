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


def load_all_strategies() -> dict[str, Type[BaseStrategy]]:
    """Import each strategy subfolder and register by Strategy.id."""
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
                logger.error("%s does not export Strategy alias", module_name)
                continue
            if not issubclass(strategy_cls, BaseStrategy):
                logger.error("%s Strategy is not a BaseStrategy subclass", module_name)
                continue
            strat_id = getattr(strategy_cls, "id", None)
            if not strat_id or strat_id == "base_strategy":
                logger.error("%s has invalid strategy id", module_name)
                continue
            _REGISTRY[strat_id] = strategy_cls
        except Exception as exc:
            logger.error("Failed to import strategy folder %s: %s", folder.name, exc)

    return _REGISTRY


def get_all_strategies() -> list[Type[BaseStrategy]]:
    load_all_strategies()
    return list(_REGISTRY.values())


def get_strategy(strategy_id: str) -> Type[BaseStrategy] | None:
    load_all_strategies()
    if strategy_id in _REGISTRY:
        return _REGISTRY[strategy_id]
    for strat_id, cls in _REGISTRY.items():
        if strategy_id in strat_id or strat_id.endswith(strategy_id):
            return cls
    module_match = next(
        (cls for sid, cls in _REGISTRY.items() if sid.split("_", 1)[-1] == strategy_id),
        None,
    )
    return module_match
