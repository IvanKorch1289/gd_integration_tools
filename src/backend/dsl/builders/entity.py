"""Entity CRUD миксин для RouteBuilder."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class EntityMixin:
    """Поведенческий миксин entity CRUD.

    Stateless: миксин использует ``self._add`` / ``self._add_lazy`` через
    MRO; собственных полей не содержит. Контракт см. в ``base.py``.
    """

    __slots__ = ()

    def entity_create(
        self,
        *,
        entity: str,
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> RouteBuilder:
        """Создать сущность через action ``<entity>.create``."""
        from src.backend.dsl.engine.processors.entity import EntityCreateProcessor

        return self._add(  # type: ignore[attr-defined]
            EntityCreateProcessor(
                entity=entity,
                payload_from=payload_from,
                result_property=result_property,
            )
        )

    def entity_get(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> RouteBuilder:
        """Прочитать сущность через action ``<entity>.get``."""
        from src.backend.dsl.engine.processors.entity import EntityGetProcessor

        return self._add(  # type: ignore[attr-defined]
            EntityGetProcessor(
                entity=entity, id_from=id_from, result_property=result_property
            )
        )

    def entity_update(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> RouteBuilder:
        """Обновить сущность через action ``<entity>.update``."""
        from src.backend.dsl.engine.processors.entity import EntityUpdateProcessor

        return self._add(  # type: ignore[attr-defined]
            EntityUpdateProcessor(
                entity=entity,
                id_from=id_from,
                payload_from=payload_from,
                result_property=result_property,
            )
        )

    def entity_delete(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> RouteBuilder:
        """Удалить сущность через action ``<entity>.delete``."""
        from src.backend.dsl.engine.processors.entity import EntityDeleteProcessor

        return self._add(  # type: ignore[attr-defined]
            EntityDeleteProcessor(
                entity=entity, id_from=id_from, result_property=result_property
            )
        )

    def entity_list(
        self,
        *,
        entity: str,
        filters_from: str | None = "body.filters",
        page: int | None = None,
        size: int | None = None,
        page_from: str | None = None,
        size_from: str | None = None,
        result_property: str = "action_result",
    ) -> RouteBuilder:
        """Получить страницу сущностей через action ``<entity>.list``."""
        from src.backend.dsl.engine.processors.entity import EntityListProcessor

        return self._add(  # type: ignore[attr-defined]
            EntityListProcessor(
                entity=entity,
                filters_from=filters_from,
                page=page,
                size=size,
                page_from=page_from,
                size_from=size_from,
                result_property=result_property,
            )
        )

    def crud_create(
        self,
        entity: str,
        *,
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> RouteBuilder:
        """Алиас к :meth:`entity_create` (R-V15-12 / 80/20 YAML)."""
        return self.entity_create(
            entity=entity, payload_from=payload_from, result_property=result_property
        )

    def crud_read(
        self,
        entity: str,
        *,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> RouteBuilder:
        """Алиас к :meth:`entity_get` (R-V15-12)."""
        return self.entity_get(
            entity=entity, id_from=id_from, result_property=result_property
        )

    def crud_update(
        self,
        entity: str,
        *,
        id_from: str = "body.id",
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> RouteBuilder:
        """Алиас к :meth:`entity_update` (R-V15-12)."""
        return self.entity_update(
            entity=entity,
            id_from=id_from,
            payload_from=payload_from,
            result_property=result_property,
        )

    def crud_delete(
        self,
        entity: str,
        *,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> RouteBuilder:
        """Алиас к :meth:`entity_delete` (R-V15-12)."""
        return self.entity_delete(
            entity=entity, id_from=id_from, result_property=result_property
        )

    def crud_list(
        self,
        entity: str,
        *,
        filters_from: str | None = "body.filters",
        page: int | None = None,
        size: int | None = None,
        result_property: str = "action_result",
    ) -> RouteBuilder:
        """Алиас к :meth:`entity_list` (R-V15-12)."""
        return self.entity_list(
            entity=entity,
            filters_from=filters_from,
            page=page,
            size=size,
            result_property=result_property,
        )
