"""Strategy package — folder-based discovery via registry."""

from .registry import get_all_strategies, get_strategy, load_all_strategies

__all__ = ["get_all_strategies", "get_strategy", "load_all_strategies"]
