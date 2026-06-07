"""Core EIP-методы: transform / filter / cdc.

Sprint 60 W4 — split из eip.py (1354 LOC).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import (
    CDCProcessor,
    FilterProcessor,
    TransformProcessor,
)

from src.backend.dsl.builders.eip._base import EIPMixinBase

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder

__all__ = ("CoreEIPsMixin",)


class CoreEIPsMixin(EIPMixinBase):
    """Базовые EIP-паттерны: transform, filter, cdc."""

    def transform(self, expression: str) -> "RouteBuilder":
        """Трансформирует body через JMESPath-выражение."""
        return self._add(TransformProcessor(expression=expression))  # type: ignore[attr-defined]

    def filter(self, predicate: Callable[[Exchange[Any]], bool]) -> "RouteBuilder":
        """Фильтрует Exchange — останавливает, если predicate=False."""
        return self._add(FilterProcessor(predicate=predicate))  # type: ignore[attr-defined]

    def cdc(
        self,
        profile: str,
        tables: list[str],
        target_action: str,
        *,
        strategy: str = "polling",
        interval: float = 5.0,
        timestamp_column: str = "updated_at",
        batch_size: int = 100,
        channel: str | None = None,
    ) -> "RouteBuilder":
        """Change Data Capture — подписка на изменения в БД.

        strategy: polling (любая БД), listen_notify (PostgreSQL), logminer (Oracle).
        """
        return self._add(  # type: ignore[attr-defined]
            CDCProcessor(
                profile=profile,
                tables=tables,
                target_action=target_action,
                strategy=strategy,
                interval=interval,
                timestamp_column=timestamp_column,
                batch_size=batch_size,
                channel=channel,
            )
        )
