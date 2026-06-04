"""Collection / Groovy DSL миксин для RouteBuilder.

Группа: collect / find_all / group_by / or_else / partition / unique /
flatten / intersect / diff / sum_by / max_by / min_by / sort_by.
Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class CollectionMixin:
    """Поведенческий миксин collection-операций для ``RouteBuilder``.

    Stateless: использует ``self._add`` / ``self._add_lazy`` через MRO;
    собственных полей не содержит.
    """

    __slots__ = ()

    def collect(
        self, *, field: str | None = None, key_fn: Callable[[Any], Any] | None = None
    ) -> RouteBuilder:
        """Извлекает поле из каждого объекта коллекции в body.

        Groovy-аналог: ``.collect { it.property }``

        Args:
            field: Имя ключа (dict) или атрибута (object) для извлечения.
            key_fn: Функция ``item -> value``; имеет приоритет над ``field``.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "CollectProcessor",
            field=field,
            key_fn=key_fn,
        )

    def find_all(
        self,
        *,
        predicate: Callable[[Any], bool] | None = None,
        condition: str | None = None,
    ) -> RouteBuilder:
        """Фильтрует коллекцию в body по условию.

        Groovy-аналог: ``.findAll { condition }``

        Args:
            predicate: Функция ``item -> bool``; имеет приоритет над ``condition``.
            condition: Строковое выражение SimpleEval (например, ``"age > 18"``).
                Контекст — ``it`` для не-dict элементов, либо ключи dict.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "FindAllProcessor",
            predicate=predicate,
            condition=condition,
        )

    def group_by(
        self, *, field: str | None = None, key_fn: Callable[[Any], Any] | None = None
    ) -> RouteBuilder:
        """Группирует коллекцию в body по полю.

        Groovy-аналог: ``.groupBy { it.property }``

        Args:
            field: Имя ключа/атрибута для группировки.
            key_fn: Функция ``item -> key``; имеет приоритет над ``field``.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "GroupByProcessor",
            field=field,
            key_fn=key_fn,
        )

    def or_else(self, *, default: Any) -> RouteBuilder:
        """Подставляет значение по умолчанию, если body пустое/None.

        Groovy-аналог: ``.orElse { defaultValue }``

        Args:
            default: Значение, заменяющее ``None``, ``""``, ``[]`` или ``{}``.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "OrElseProcessor",
            default=default,
        )

    # ── Wave 1: Sprint 37 Foundation ──

    def partition(
        self,
        *,
        field: str | None = None,
        predicate: Callable[[Any], bool] | None = None,
    ) -> RouteBuilder:
        """Разбивает коллекцию на два списка: подходящие и нет.

        Groovy-аналог: ``.partition { condition }``

        Args:
            field: Имя поля для truthiness-проверки (dict/object).
            predicate: Функция ``item -> bool``; имеет приоритет над ``field``.

        Returns:
            ``RouteBuilder`` с процессором, который заменяет body на
            ``[matching, non_matching]``.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "PartitionProcessor",
            field=field,
            predicate=predicate,
        )

    def unique(
        self, *, field: str | None = None, key_fn: Callable[[Any], Any] | None = None
    ) -> RouteBuilder:
        """Уникальные элементы коллекции.

        Args:
            field: Имя поля для уникальности (по значению поля).
            key_fn: Функция ``item -> key``; имеет приоритет над ``field``.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "UniqueProcessor",
            field=field,
            key_fn=key_fn,
        )

    def flatten(self, *, depth: int = 1) -> RouteBuilder:
        """Расплющивает nested lists в body.

        Args:
            depth: Глубина расплющивания (default 1).
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "FlattenProcessor",
            depth=depth,
        )

    def intersect(self, other: list[Any]) -> RouteBuilder:
        """Пересечение body с другим списком.

        Args:
            other: Список для пересечения.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "IntersectProcessor",
            other=other,
        )

    def diff(self, other: list[Any]) -> RouteBuilder:
        """Разность body с другим списком.

        Args:
            other: Список для вычитания.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "DiffProcessor",
            other=other,
        )

    def sum_by(self, field: str) -> RouteBuilder:
        """Сумма по полю элементов коллекции.

        Args:
            field: Имя числового поля.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "SumByProcessor",
            field=field,
        )

    def max_by(self, field: str) -> RouteBuilder:
        """Максимум по полю элементов коллекции.

        Args:
            field: Имя поля для сравнения.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "MaxByProcessor",
            field=field,
        )

    def min_by(self, field: str) -> RouteBuilder:
        """Минимум по полю элементов коллекции.

        Args:
            field: Имя поля для сравнения.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "MinByProcessor",
            field=field,
        )

    def sort_by(self, field: str, *, reverse: bool = False) -> RouteBuilder:
        """Сортировка коллекции по полю.

        Args:
            field: Имя поля для сортировки.
            reverse: Обратный порядок.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip.collection",
            "SortByProcessor",
            field=field,
            reverse=reverse,
        )
