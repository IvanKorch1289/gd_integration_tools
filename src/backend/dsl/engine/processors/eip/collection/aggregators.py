"""S57 W3 — aggregators.py part of collection EIP decomp.

Classes: SumByProcessor, MaxByProcessor, MinByProcessor, SortByProcessor.

aggregate functions (sumBy, maxBy, minBy, sortBy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.eip.collection.collect import _resolve_field

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
        """Sum numeric field across collection, output = total (float)."""
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
        """Сериализует sum_by конфиг в JSON-Schema spec."""
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
        """Find max element по field, output = element (fallback: original body)."""
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
        """Сериализует max_by конфиг в JSON-Schema spec."""
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
        """Find min element по field, output = element (fallback: original body)."""
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
        """Сериализует min_by конфиг в JSON-Schema spec."""
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
        """Sort collection по field (asc/desc), output = sorted list (fallback: original)."""
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
        """Сериализует sort_by конфиг в JSON-Schema spec."""
        return {"sort_by": {"field": self._field, "reverse": self._reverse}}
