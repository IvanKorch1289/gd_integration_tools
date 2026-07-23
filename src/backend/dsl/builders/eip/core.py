"""Core EIP-методы: transform / filter.

Sprint 60 W4 — split из eip.py (1354 LOC).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from src.backend.dsl.builders.eip._base import EIPMixinBase
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import (
    FilterProcessor,
    TransformProcessor,
)

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder

__all__ = ("CoreEIPsMixin",)


class CoreEIPsMixin(EIPMixinBase):
    """Базовые EIP-паттерны: transform, filter."""

    def transform(self, expression: str) -> "RouteBuilder":
        """Трансформирует body через JMESPath-выражение."""
        return cast(
            "RouteBuilder",
            self._add(TransformProcessor(expression=expression)),  # type: ignore[attr-defined]
        )

    def filter(self, predicate: Callable[[Exchange[Any]], bool]) -> "RouteBuilder":
        """Фильтрует Exchange — останавливает, если predicate=False."""
        return cast(
            "RouteBuilder",
            self._add(FilterProcessor(predicate=predicate)),  # type: ignore[attr-defined]
        )
