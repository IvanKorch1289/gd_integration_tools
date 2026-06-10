"""S57 W3 — aggregators.py part of collection EIP decomp.

Classes: SumByProcessor, MaxByProcessor, MinByProcessor, SortByProcessor.

aggregate functions (sumBy, maxBy, minBy, sortBy).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

class SumByProcessor(BaseProcessor):
    """Сумма по полю элементов коллекции.

    Usage::

        .sum_by(field="amount")
    """

    def __init__(self, *, field: str, name: str | None = None) -> None:
        super().__init__(name=name or f"sum_by({field})")
        self._field = field

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, list):
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return

        total = 0.0
        for item in body:
            value = _resolve_field(item, self._field)
            if isinstance(value, (int, float)):
                total += value

        exchange.set_out(body=total, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        return {"sum_by": {"field": self._field}}

class MaxByProcessor(BaseProcessor):
    """Максимум по полю элементов коллекции.

    Usage::

        .max_by(field="score")
    """

    def __init__(self, *, field: str, name: str | None = None) -> None:
        super().__init__(name=name or f"max_by({field})")
        self._field = field

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, list) or not body:
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return

        try:
            result = max(body, key=lambda item: _resolve_field(item, self._field))
        except Exception:
            result = body
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        return {"max_by": {"field": self._field}}

class MinByProcessor(BaseProcessor):
    """Минимум по полю элементов коллекции.

    Usage::

        .min_by(field="price")
    """

    def __init__(self, *, field: str, name: str | None = None) -> None:
        super().__init__(name=name or f"min_by({field})")
        self._field = field

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, list) or not body:
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return

        try:
            result = min(body, key=lambda item: _resolve_field(item, self._field))
        except Exception:
            result = body
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        return {"min_by": {"field": self._field}}

class SortByProcessor(BaseProcessor):
    """Сортировка коллекции по полю.

    Usage::

        .sort_by(field="name", reverse=False)
    """

    def __init__(
        self, *, field: str, reverse: bool = False, name: str | None = None
    ) -> None:
        super().__init__(name=name or f"sort_by({field}, reverse={reverse})")
        self._field = field
        self._reverse = reverse

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, list):
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return

        try:
            result = sorted(
                body,
                key=lambda item: _resolve_field(item, self._field),
                reverse=self._reverse,
            )
        except Exception:
            result = body
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        return {"sort_by": {"field": self._field, "reverse": self._reverse}}

