"""S57 W3 — collect.py part of collection EIP decomp.

Classes: CollectProcessor, FindAllProcessor, GroupByProcessor.

basic collection operations (collect, findAll, groupBy).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

class CollectProcessor(BaseProcessor):
    """Извлекает поле из каждого объекта коллекции.

    Groovy-аналог: ``.collect { it.property }``

    Usage::

        .collect(field="name")
        .collect(key_fn=lambda item: item["name"].upper())
    """

    def __init__(
        self,
        *,
        field: str | None = None,
        key_fn: Callable[[Any], Any] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"collect({field or 'key_fn'})")
        self._field = field
        self._key_fn = key_fn

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Извлекает поле или применяет функцию к каждому элементу коллекции."""
        body = exchange.in_message.body
        if not isinstance(body, list):
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return

        if self._key_fn is not None:
            result = [self._key_fn(item) for item in body]
        elif self._field is not None:
            result = [
                item.get(self._field)
                if isinstance(item, dict)
                else getattr(item, self._field, None)
                for item in body
            ]
        else:
            result = body

        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Возвращает JSON-спецификацию процессора."""
        return {
            "collect": {
                "field": self._field,
                "key_fn": self._key_fn.__name__ if self._key_fn else None,
            }
        }

class FindAllProcessor(BaseProcessor):
    """Фильтрует коллекцию по условию.

    Groovy-аналог: ``.findAll { condition }``

    Usage::

        .find_all(predicate=lambda item: item["age"] > 18)
        .find_all(condition="age > 18")
    """

    def __init__(
        self,
        *,
        predicate: Callable[[Any], bool] | None = None,
        condition: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "find_all")
        self._predicate = predicate
        self._condition = condition

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Фильтрует коллекцию по предикату или условию."""
        body = exchange.in_message.body
        if not isinstance(body, list):
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return

        if self._predicate is not None:
            result = [item for item in body if self._predicate(item)]
        elif self._condition is not None:
            from simpleeval import SimpleEval  # lazy-import — S4 R-V15-4

            result = []
            for item in body:
                ctx = {"it": item} if not isinstance(item, dict) else dict(item)
                try:
                    if bool(SimpleEval(names=ctx).eval(self._condition)):
                        result.append(item)
                except Exception:
                    continue
        else:
            result = body

        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Возвращает JSON-спецификацию процессора."""
        return {
            "find_all": {
                "predicate": self._predicate.__name__ if self._predicate else None,
                "condition": self._condition,
            }
        }

class GroupByProcessor(BaseProcessor):
    """Группирует коллекцию по полю.

    Groovy-аналог: ``.groupBy { it.property }``

    Usage::

        .group_by(field="category")
        .group_by(key_fn=lambda item: item["category"][:3])
    """

    def __init__(
        self,
        *,
        field: str | None = None,
        key_fn: Callable[[Any], Any] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"group_by({field or 'key_fn'})")
        self._field = field
        self._key_fn = key_fn

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Группирует элементы коллекции по ключу."""
        body = exchange.in_message.body
        if not isinstance(body, list):
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return

        result: dict[Any, list[Any]] = {}
        for item in body:
            if self._key_fn is not None:
                key = self._key_fn(item)
            elif self._field is not None:
                key = (
                    item.get(self._field)
                    if isinstance(item, dict)
                    else getattr(item, self._field, None)
                )
            else:
                key = item
            result.setdefault(key, []).append(item)

        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Возвращает JSON-спецификацию процессора."""
        return {
            "group_by": {
                "field": self._field,
                "key_fn": self._key_fn.__name__ if self._key_fn else None,
            }
        }

def _resolve_field(item: Any, field: str | None) -> Any:
    if field is None:
        return item
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field, None)

