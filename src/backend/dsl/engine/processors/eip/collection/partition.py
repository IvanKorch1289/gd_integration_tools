"""S57 W3 — partition.py part of collection EIP decomp.

Classes: PartitionProcessor, OrElseProcessor, FlattenProcessor, UniqueProcessor.

partition + orElse + flatten + unique.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.eip.collection.collect import _resolve_field

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


class PartitionProcessor(BaseProcessor):
    """Разбивает коллекцию на два списка: подходящие и нет.

    Usage::

        .partition(field="active")
        .partition(predicate=lambda item: item["age"] >= 18)
    """

    def __init__(
        self,
        *,
        field: str | None = None,
        predicate: Callable[[Any], bool] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"partition({field or 'predicate'})")
        self._field = field
        self._predicate = predicate

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, list):
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return

        matched: list[Any] = []
        unmatched: list[Any] = []
        for item in body:
            if self._predicate is not None:
                ok = bool(self._predicate(item))
            elif self._field is not None:
                ok = bool(_resolve_field(item, self._field))
            else:
                ok = bool(item)
            (matched if ok else unmatched).append(item)

        exchange.set_out(
            body=[matched, unmatched], headers=dict(exchange.in_message.headers)
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "partition": {
                "field": self._field,
                "predicate": self._predicate.__name__ if self._predicate else None,
            }
        }


class OrElseProcessor(BaseProcessor):
    """Значение по умолчанию, если body None или пустое.

    Groovy-аналог: ``.orElse { defaultValue }``

    Usage::

        .or_else(default="N/A")
        .or_else(default=[])
    """

    def __init__(self, *, default: Any, name: str | None = None) -> None:
        super().__init__(name=name or "or_else")
        self._default = default

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Подставляет значение по умолчанию, если body пустое."""
        body = exchange.in_message.body
        if body is None or body == "" or body == [] or body == {}:
            exchange.set_out(
                body=self._default, headers=dict(exchange.in_message.headers)
            )
        else:
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Возвращает JSON-спецификацию процессора."""
        return {"or_else": {"default": self._default}}


class FlattenProcessor(BaseProcessor):
    """Расплющивает nested lists.

    Usage::

        .flatten(depth=1)
        .flatten(depth=2)
    """

    def __init__(self, *, depth: int = 1, name: str | None = None) -> None:
        super().__init__(name=name or f"flatten({depth})")
        self._depth = depth

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, list):
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return

        def _flatten(items: list[Any], d: int) -> list[Any]:
            result: list[Any] = []
            for item in items:
                if isinstance(item, list) and d > 0:
                    result.extend(_flatten(item, d - 1))
                else:
                    result.append(item)
            return result

        exchange.set_out(
            body=_flatten(body, self._depth), headers=dict(exchange.in_message.headers)
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {"flatten": {"depth": self._depth}}


class UniqueProcessor(BaseProcessor):
    """Уникальные элементы коллекции.

    Usage::

        .unique(field="email")
        .unique(key_fn=lambda item: item["email"].lower())
    """

    def __init__(
        self,
        *,
        field: str | None = None,
        key_fn: Callable[[Any], Any] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"unique({field or 'key_fn'})")
        self._field = field
        self._key_fn = key_fn

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, list):
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return

        seen: set[Any] = set()
        result: list[Any] = []
        for item in body:
            if self._key_fn is not None:
                key = self._key_fn(item)
            elif self._field is not None:
                key = _resolve_field(item, self._field)
            else:
                key = item
            if key not in seen:
                seen.add(key)
                result.append(item)

        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "unique": {
                "field": self._field,
                "key_fn": self._key_fn.__name__ if self._key_fn else None,
            }
        }
