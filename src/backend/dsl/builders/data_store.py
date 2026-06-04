"""DataStore миксин для RouteBuilder.

Простой in-memory key-value store в рамках Exchange.properties.
Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class DataStoreStepMixin:
    """Поведенческий миксин data-store операций для ``RouteBuilder`` (S22).

    Step-based variant: добавляет ``DataStoreSetProcessor``/Get/Delete в
    pipeline. Для n8n-style in-memory KV объекта см. :class:`DataStoreMixin`
    в :mod:`src.backend.dsl.builders.data_store_mixin`.
    """

    __slots__ = ()

    def data_store_set(self, key: str, value: Any) -> RouteBuilder:
        """Сохраняет значение в in-memory store Exchange.

        Args:
            key: Ключ в хранилище.
            value: Значение (Any, сериализуемое).
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.data_store",
            "DataStoreSetProcessor",
            key=key,
            value=value,
        )

    def data_store_get(
        self,
        key: str,
        *,
        default: Any = None,
        result_property: str = "data_store_value",
    ) -> RouteBuilder:
        """Читает значение из in-memory store Exchange.

        Args:
            key: Ключ в хранилище.
            default: Значение по умолчанию, если ключ отсутствует.
            result_property: Имя property для записи результата.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.data_store",
            "DataStoreGetProcessor",
            key=key,
            default=default,
            result_property=result_property,
        )

    def data_store_delete(self, key: str) -> RouteBuilder:
        """Удаляет ключ из in-memory store Exchange."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.data_store",
            "DataStoreDeleteProcessor",
            key=key,
        )
