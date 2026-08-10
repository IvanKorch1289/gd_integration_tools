"""S175 Phase 2: EntityListProcessor (full implementation).

Split из entity.py godfile.
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.entity._legacy import _BaseEntityProcessor

from ._resolve import _resolve

__all__ = ("EntityListProcessor",)


class EntityListProcessor(_BaseEntityProcessor):
    """Возвращает страницу сущностей через action ``<entity>.list``.

    Args:
        entity: Имя сущности.
        filters_from: Выражение извлечения фильтров (default ``body.filters``).
        page: Номер страницы (1-based) или ``None``.
        size: Размер страницы или ``None``.
        page_from: Альтернативно — выражение из exchange.
        size_from: Альтернативно — выражение из exchange.
        result_property: Имя property для записи результата.

    """

    _verb = "list"

    def __init__(
        self,
        *,
        entity: str,
        filters_from: str | None = "body.filters",
        page: int | None = None,
        size: int | None = None,
        page_from: str | None = None,
        size_from: str | None = None,
        result_property: str = "action_result",
        name: str | None = None,
    ) -> None:
        super().__init__(entity=entity, result_property=result_property, name=name)
        self._filters_from = filters_from
        self._page = page
        self._size = size
        self._page_from = page_from
        self._size_from = size_from

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Resolve filters + pagination, dispatch entity list query."""
        filters = _resolve(exchange, self._filters_from) or {}
        page = self._page
        if self._page_from is not None:
            value = _resolve(exchange, self._page_from)
            if value is not None:
                page = int(value)
        size = self._size
        if self._size_from is not None:
            value = _resolve(exchange, self._size_from)
            if value is not None:
                size = int(value)

        payload: dict[str, Any] = {
            "filters": filters if isinstance(filters, dict) else {},
        }
        if page is not None:
            payload["page"] = page
        if size is not None:
            payload["size"] = size
        await self._dispatch(payload, context, exchange)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует entity_list конфиг в JSON-Schema spec."""
        spec: dict[str, Any] = {
            "entity": self._entity,
            "result_property": self._result_property,
        }
        if self._filters_from is not None:
            spec["filters_from"] = self._filters_from
        if self._page is not None:
            spec["page"] = self._page
        if self._size is not None:
            spec["size"] = self._size
        if self._page_from is not None:
            spec["page_from"] = self._page_from
        if self._size_from is not None:
            spec["size_from"] = self._size_from
        return {"entity_list": spec}
