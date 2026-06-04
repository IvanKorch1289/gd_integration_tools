"""K3 W1 — :class:`CollectionMixin`: 9 Groovy Collection DSL методов.

Предоставляет 9 Groovy-style collection operations, чтобы закрыть
Sprint 5+ Groovy DSL gap. Все методы pure (нет side-effects на inputs).

Groovy → CollectionMixin mapping:
- .collect{ it.field }    → .collect(field="name")
- .findAll{ cond }        → .find_all(predicate=callable | field="x", value=y)
- .find{ cond }           → .find(predicate=callable | field="x", value=y)
- .groupBy{ it.field }    → .group_by(field="category")
- .sort{ it.field }       → .sort(field="name", reverse=False)
- .each{ action }         → .each(action=callable) → returns original list
- .flatten()              → .flatten(levels=1)
- .unique{ it.field }     → .unique(field="email")
- .plus(other)            → .plus(other=list|tuple|set)

Constraints:
- ``__slots__ = ()`` (stateless, no instance state)
- Static methods, callable on any iterable
- All methods return new collection, НЕ mutate input
- Stdlib only (no boltons, no external deps)
- Thread-safe (pure functions, no shared state)
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


class CollectionMixin:
    """Mixin с 9 Groovy Collection DSL методами.

    Использование:
        CollectionMixin.collect([{"name": "a"}, {"name": "b"}], field="name")
        # → ["a", "b"]
    """

    __slots__ = ()

    # --- 1. collect ---
    @staticmethod
    def collect(
        items: Iterable[dict[str, Any]] | Iterable[Any],
        field: str | None = None,
    ) -> list[Any]:
        """Groovy: ``.collect { it.field }`` — извлечь field из каждого dict.

        Args:
            items: Iterable of dicts (or primitives).
            field: Dot-separated field name (top-level for now). None = collect as-is.

        Returns:
            List of field values (or items if field=None).
        """
        items = list(items) if items is not None else []
        if field is None:
            return list(items)
        return [
            item.get(field) if isinstance(item, dict) else getattr(item, field, None)
            for item in items
        ]

    # --- 2. find_all ---
    @staticmethod
    def find_all(
        items: Iterable[Any],
        predicate: Callable[[Any], bool] | None = None,
        *,
        field: str | None = None,
        value: Any = None,
    ) -> list[Any]:
        """Groovy: ``.findAll { cond }`` — фильтр по условию.

        Args:
            items: Iterable.
            predicate: Callable(item) -> bool. Mutually exclusive with field/value.
            field: If set, filter where item[field] == value.
            value: Value to compare against (used with field).

        Returns:
            Filtered list.
        """
        items = list(items) if items is not None else []
        if predicate is not None:
            return [item for item in items if predicate(item)]
        if field is not None:
            return [
                item
                for item in items
                if (isinstance(item, dict) and item.get(field) == value)
                or (not isinstance(item, dict) and getattr(item, field, None) == value)
            ]
        return list(items)

    # --- 3. find ---
    @staticmethod
    def find(
        items: Iterable[Any],
        predicate: Callable[[Any], bool] | None = None,
        *,
        field: str | None = None,
        value: Any = None,
    ) -> Any:
        """Groovy: ``.find { cond }`` — первый matching element.

        Returns:
            First matching element, or None if not found.
        """
        items = list(items) if items is not None else []
        if predicate is not None:
            for item in items:
                if predicate(item):
                    return item
            return None
        if field is not None:
            for item in items:
                if (isinstance(item, dict) and item.get(field) == value) or (
                    not isinstance(item, dict)
                    and getattr(item, field, None) == value
                ):
                    return item
            return None
        return None

    # --- 4. group_by ---
    @staticmethod
    def group_by(
        items: Iterable[dict[str, Any]] | Iterable[Any],
        field: str,
    ) -> dict[Any, list[Any]]:
        """Groovy: ``.groupBy { it.field }`` — группировка по field.

        Returns:
            Dict[group_key, list_of_items].
        """
        items = list(items) if items is not None else []
        result: dict[Any, list[Any]] = {}
        for item in items:
            if isinstance(item, dict):
                key = item.get(field)
            else:
                key = getattr(item, field, None)
            result.setdefault(key, []).append(item)
        return result

    # --- 5. sort ---
    @staticmethod
    def sort(
        items: Iterable[dict[str, Any]] | Iterable[Any],
        field: str | None = None,
        *,
        reverse: bool = False,
    ) -> list[Any]:
        """Groovy: ``.sort { it.field }`` — сортировка по field.

        Args:
            items: Iterable of dicts or objects.
            field: If None, sort primitives directly.
            reverse: If True, descending order.

        Returns:
            Sorted list (new list, input not mutated).
        """
        items = list(items) if items is not None else []
        if field is None:
            return sorted(items, reverse=reverse)

        def _key(item: Any) -> Any:
            if isinstance(item, dict):
                return item.get(field)
            return getattr(item, field, None)

        return sorted(items, key=_key, reverse=reverse)

    # --- 6. each ---
    @staticmethod
    def each(
        items: Iterable[Any],
        action: Callable[[Any], Any],
    ) -> list[Any]:
        """Groovy: ``.each { action }`` — side-effect iter.

        Returns:
            Original list (Groovy convention).
        """
        items = list(items) if items is not None else []
        for item in items:
            action(item)
        return items

    # --- 7. flatten ---
    @staticmethod
    def flatten(
        items: Iterable[Any],
        levels: int = 1,
    ) -> list[Any]:
        """Groovy: ``.flatten()`` — flatten nested.

        Args:
            items: Nested iterable.
            levels: How many levels to flatten (1 by default).

        Returns:
            Flattened list.
        """
        items = list(items) if items is not None else []
        if levels <= 0:
            return list(items)
        result: list[Any] = []
        for item in items:
            if isinstance(item, (list, tuple, set, frozenset)):
                if levels == 1:
                    result.extend(item)
                else:
                    result.extend(CollectionMixin.flatten(item, levels - 1))
            else:
                result.append(item)
        return result

    # --- 8. unique ---
    @staticmethod
    def unique(
        items: Iterable[Any],
        field: str | None = None,
    ) -> list[Any]:
        """Groovy: ``.unique { it.field }`` — дедупликация.

        Args:
            items: Iterable of dicts or primitives.
            field: If set, dedup by item[field]. Else dedup primitives.

        Returns:
            Deduped list (order preserved).
        """
        items = list(items) if items is not None else []
        if field is None:
            seen: set[Any] = set()
            result: list[Any] = []
            for item in items:
                try:
                    if item not in seen:
                        seen.add(item)
                        result.append(item)
                except TypeError:
                    # Unhashable (e.g. dict, list) — keep
                    result.append(item)
            return result
        seen_keys: set[Any] = set()
        result = []
        for item in items:
            if isinstance(item, dict):
                key = item.get(field)
            else:
                key = getattr(item, field, None)
            try:
                if key not in seen_keys:
                    seen_keys.add(key)
                    result.append(item)
            except TypeError:
                result.append(item)
        return result

    # --- 9. plus ---
    @staticmethod
    def plus(
        items: Iterable[Any],
        other: Iterable[Any],
    ) -> list[Any]:
        """Groovy: ``.plus(other)`` — объединение.

        Returns:
            New list with items + other.
        """
        items = list(items) if items is not None else []
        other = list(other) if other is not None else []
        return items + other


__all__ = ["CollectionMixin"]
