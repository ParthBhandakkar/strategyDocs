"""Strategy package — folder-based discovery via registry."""

from .registry import get_strategy, get_all_strategies, list_strategy_ids, load_all_strategies

__all__ = ["get_strategy", "get_all_strategies", "list_strategy_ids", "load_all_strategies"]
