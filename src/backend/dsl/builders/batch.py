"""Batch DB миксин для RouteBuilder.

Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class BatchMixin:
    """Поведенческий миксин batch-операций БД для ``RouteBuilder``."""

    __slots__ = ()

    def batch_insert(
        self,
        table: str,
        items: list[dict[str, Any]] | None = None,
        *,
        profile: str = "default",
    ) -> RouteBuilder:
        """Batch INSERT через SQLAlchemy core.

        Args:
            table: Имя таблицы.
            items: Список dict для вставки. ``None`` — берётся из ``body``.
            profile: Имя профиля внешней БД.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.batch",
            "BatchInsertProcessor",
            table=table,
            items=items,
            profile=profile,
        )

    def batch_update(
        self,
        table: str,
        items: list[dict[str, Any]] | None = None,
        *,
        key_field: str = "id",
        profile: str = "default",
    ) -> RouteBuilder:
        """Batch UPDATE через SQLAlchemy core.

        Args:
            table: Имя таблицы.
            items: Список dict для обновления. ``None`` — берётся из ``body``.
            key_field: Поле для WHERE-clause.
            profile: Имя профиля внешней БД.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.batch",
            "BatchUpdateProcessor",
            table=table,
            items=items,
            key_field=key_field,
            profile=profile,
        )

    def batch_delete(
        self,
        table: str,
        ids: list[Any] | None = None,
        *,
        key_field: str = "id",
        profile: str = "default",
    ) -> RouteBuilder:
        """Batch DELETE через SQLAlchemy core.

        Args:
            table: Имя таблицы.
            ids: Список ID для удаления. ``None`` — берётся из ``body``.
            key_field: Поле для WHERE-clause.
            profile: Имя профиля внешней БД.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.batch",
            "BatchDeleteProcessor",
            table=table,
            ids=ids,
            key_field=key_field,
            profile=profile,
        )
