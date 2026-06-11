"""S57 W3 — set_ops.py part of collection EIP decomp.

Classes: IntersectProcessor, DiffProcessor.

set algebra (intersect, diff).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


class IntersectProcessor(BaseProcessor):
    """Пересечение с другим списком.

    Usage::

        .intersect(other=[1, 2, 3])
    """

    def __init__(self, *, other: list[Any], name: str | None = None) -> None:
        super().__init__(name=name or "intersect")
        self._other = other

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, list):
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return

        other_set = set(self._other)
        exchange.set_out(
            body=[item for item in body if item in other_set],
            headers=dict(exchange.in_message.headers),
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {"intersect": {"other": self._other}}


class DiffProcessor(BaseProcessor):
    """Разность с другим списком.

    Usage::

        .diff(other=[1, 2, 3])
    """

    def __init__(self, *, other: list[Any], name: str | None = None) -> None:
        super().__init__(name=name or "diff")
        self._other = other

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, list):
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return

        other_set = set(self._other)
        exchange.set_out(
            body=[item for item in body if item not in other_set],
            headers=dict(exchange.in_message.headers),
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {"diff": {"other": self._other}}
