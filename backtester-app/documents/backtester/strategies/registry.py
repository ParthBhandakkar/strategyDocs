"""
Folder-based strategy discovery.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Type

from backtester.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

SKIP_DIRS = {"base", "registry", "__pycache__"}


def discover_strategies() -> dict[str, Type[BaseStrategy]]:
    strategies: dict[str, Type[BaseStrategy]] = {}
    root = Path(__file__).resolve().parent

    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or folder.name in SKIP_DIRS:
            continue
        init_file = folder / "__init__.py"
        if not init_file.exists():
            logger.warning("Skipping strategy folder without __init__.py: %s", folder.name)
            continue
        module_name = f"backtester.strategies.{folder.name}"
        try:
            module = importlib.import_module(module_name)
            strategy_cls = getattr(module, "Strategy", None)
            if strategy_cls is None:
                logger.error("Strategy folder %s missing Strategy export", folder.name)
                continue
            instance = strategy_cls()
            strategy_id = getattr(instance, "id", "")
            if not strategy_id:
                logger.error("Strategy in %s missing id", folder.name)
                continue
            strategies[strategy_id] = strategy_cls
        except Exception as exc:
            logger.exception("Failed importing strategy folder %s: %s", folder.name, exc)
            raise

    return strategies


def get_strategy(strategy_id: str) -> BaseStrategy:
    registry = discover_strategies()
    if strategy_id in registry:
        return registry[strategy_id]()

    for key, strategy_cls in registry.items():
        if key.endswith(f"_{strategy_id}") or key.split("_", 1)[-1] == strategy_id:
            return strategy_cls()

    available = ", ".join(sorted(registry)) or "(none)"
    raise KeyError(f"Unknown strategy '{strategy_id}'. Available: {available}")
