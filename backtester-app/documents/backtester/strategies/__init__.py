"""Folder-based strategy package."""

from .registry import discover_strategies, get_strategy

__all__ = ["discover_strategies", "get_strategy"]
