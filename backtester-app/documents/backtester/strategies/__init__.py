"""Strategy package with folder-based discovery."""

from .registry import get_all_strategies, get_strategy, list_strategy_metadata, load_all_strategies

__all__ = ["get_all_strategies", "get_strategy", "list_strategy_metadata", "load_all_strategies"]
