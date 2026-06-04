"""Content / transformation миксин для RouteBuilder.

Группа: enrich / wire_tap / multicast / recipient_list /
content_filter (alias filter) / content_transform (alias transform).
Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import (
    BaseProcessor,
    EnrichProcessor,
    FilterProcessor,
    MulticastProcessor,
    RecipientListProcessor,
    TransformProcessor,
    WireTapProcessor,
)

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class ContentMixin:
    """Поведенческий миксин content-операций для ``RouteBuilder``.

    Stateless: использует ``self._add`` через MRO;
    собственных полей не содержит.
    """

    __slots__ = ()

    def enrich(
        self,
        action: str,
        *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "enrichment",
    ) -> RouteBuilder:
        """Enrich: вызывает action и сохраняет результат в property."""
        return self._add(  # type: ignore[attr-defined]
            EnrichProcessor(
                action=action,
                payload_factory=payload_factory,
                result_property=result_property,
            )
        )

    def wire_tap(self, tap_processors: list[BaseProcessor]) -> RouteBuilder:
        """Wire Tap: копия Exchange в побочный канал без влияния на основной поток."""
        return self._add(WireTapProcessor(tap_processors=tap_processors))  # type: ignore[attr-defined]

    def multicast(
        self,
        branches: list[list[BaseProcessor]],
        *,
        strategy: str = "all",
        stop_on_error: bool = False,
    ) -> RouteBuilder:
        """Multicast: fan-out на flat list процессор-групп + aggregation."""
        return self._add(  # type: ignore[attr-defined]
            MulticastProcessor(
                branches=branches, strategy=strategy, stop_on_error=stop_on_error
            )
        )

    def recipient_list(
        self,
        recipients_expression: Callable[[Exchange[Any]], list[str]],
        *,
        parallel: bool = True,
    ) -> RouteBuilder:
        """Recipient List: динамический fan-out на список маршрутов."""
        return self._add(  # type: ignore[attr-defined]
            RecipientListProcessor(
                recipients_expression=recipients_expression, parallel=parallel
            )
        )

    def content_filter(
        self, predicate: Callable[[Exchange[Any]], bool]
    ) -> RouteBuilder:
        """Alias для :meth:`filter` — фильтрует Exchange, останавливает если False."""
        return self._add(FilterProcessor(predicate=predicate))  # type: ignore[attr-defined]

    def content_transform(self, expression: str) -> RouteBuilder:
        """Alias для :meth:`transform` — трансформирует body через JMESPath-выражение."""
        return self._add(TransformProcessor(expression=expression))  # type: ignore[attr-defined]
