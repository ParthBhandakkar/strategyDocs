"""Strategy package — folder-based discovery via registry."""

from .registry import get_registry, get_strategy, load_all_strategies

__all__ = ["get_registry", "get_strategy", "load_all_strategies"]
