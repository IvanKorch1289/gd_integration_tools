"""Groovy DSL Collection processors — P1 gap fill (S36) + Sprint 37 Foundation.

Реализует ключевые методы Groovy Collection DSL, отсутствующие
в gd_integration_tools:

* ``.collect(field="name")`` → :class:`CollectProcessor`
* ``.find_all(condition="age > 18")`` → :class:`FindAllProcessor`
* ``.group_by(field="category")`` → :class:`GroupByProcessor`
* ``.or_else(default="N/A")`` → :class:`OrElseProcessor`
* ``.partition(field="active")`` → :class:`PartitionProcessor`
* ``.unique(field="email")`` → :class:`UniqueProcessor`
* ``.flatten(depth=1)`` → :class:`FlattenProcessor`
* ``.intersect(other)`` → :class:`IntersectProcessor`
* ``.diff(other)`` → :class:`DiffProcessor`
* ``.sum_by(field="amount")`` → :class:`SumByProcessor`
* ``.max_by(field="score")`` → :class:`MaxByProcessor`
* ``.min_by(field="price")`` → :class:`MinByProcessor`
* ``.sort_by(field="name")`` → :class:`SortByProcessor`

Все процессоры работают над ``exchange.in_message.body``:
ожидают ``list | dict | None`` и производят новый body.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = (
    "CollectProcessor",
    "DiffProcessor",
    "FindAllProcessor",
    "FlattenProcessor",
    "GroupByProcessor",
    "IntersectProcessor",
    "MaxByProcessor",
    "MinByProcessor",
    "OrElseProcessor",
    "PartitionProcessor",
    "SortByProcessor",
    "SumByProcessor",
    "UniqueProcessor",
)


def _resolve_field(item: Any, field: str | None) -> Any:
    if field is None:
        return item
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field, None)


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


# ── Sprint 37 Foundation processors ──


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
