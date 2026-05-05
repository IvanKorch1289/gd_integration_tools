"""Entity CRUD процессоры (Wave 11).

Тонкие обёртки над :class:`DispatchActionProcessor` с конвенцией имён
actions: ``<entity>.create``, ``<entity>.get``, ``<entity>.update``,
``<entity>.delete``, ``<entity>.list``. Каждое действие должно быть
зарегистрировано в :class:`ActionHandlerRegistry` со стандартной сигнатурой.

Использование в YAML::

    - entity_create: {entity: orders, payload_from: body}
    - entity_get:    {entity: orders, id_from: body.id}
    - entity_update: {entity: orders, id_from: body.id, payload_from: body}
    - entity_delete: {entity: orders, id_from: body.id}
    - entity_list:   {entity: orders, filters_from: body.filters, page: 1, size: 50}
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.schemas.invocation import ActionCommandSchema

__all__ = (
    "EntityCreateProcessor",
    "EntityGetProcessor",
    "EntityUpdateProcessor",
    "EntityDeleteProcessor",
    "EntityListProcessor",
)

_logger = logging.getLogger("dsl.entity")


def _walk(node: Any, parts: list[str]) -> Any:
    for part in parts:
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def _resolve(exchange: Exchange[Any], expression: str | None) -> Any:
    """Извлекает значение из exchange по ``namespace.path`` (см. ``express._common``)."""
    if not expression:
        return None
    if expression.startswith("header."):
        return exchange.in_message.headers.get(expression.removeprefix("header."))
    parts = expression.split(".")
    head, tail = parts[0], parts[1:]
    if head == "body":
        body = exchange.in_message.body
        if isinstance(body, dict):
            return _walk(body, tail) if tail else body
        return body if not tail else None
    if head == "properties":
        return _walk(exchange.properties, tail) if tail else exchange.properties
    if head == "result":
        result = exchange.get_property("action_result")
        return _walk(result, tail) if tail else result
    return _walk(exchange.properties, parts)


class _BaseEntityProcessor(BaseProcessor):
    """Общая логика: dispatch ``<entity>.<verb>`` через action registry."""

    _verb: str = ""

    def __init__(
        self,
        *,
        entity: str,
        result_property: str = "action_result",
        name: str | None = None,
    ) -> None:
        if not entity or "." in entity:
            raise ValueError(
                f"{type(self).__name__}: entity должна быть именем без точек, "
                f"получено {entity!r}"
            )
        super().__init__(name=name or f"entity_{self._verb}:{entity}")
        self._entity = entity
        self._result_property = result_property

    @property
    def _action(self) -> str:
        return f"{self._entity}.{self._verb}"

    async def _dispatch(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
        exchange: Exchange[Any],
    ) -> None:
        command = ActionCommandSchema(action=self._action, payload=payload)
        result = await context.action_registry.dispatch(command)
        exchange.set_property(self._result_property, result)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class EntityCreateProcessor(_BaseEntityProcessor):
    """Создаёт сущность через action ``<entity>.create``.

    Args:
        entity: Имя сущности (``orders``, ``users``, ...).
        payload_from: Выражение извлечения payload (default ``body``).
        result_property: Имя property для записи созданной сущности.
    """

    _verb = "create"

    def __init__(
        self,
        *,
        entity: str,
        payload_from: str = "body",
        result_property: str = "action_result",
        name: str | None = None,
    ) -> None:
        super().__init__(entity=entity, result_property=result_property, name=name)
        self._payload_from = payload_from

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        payload = _resolve(exchange, self._payload_from)
        if not isinstance(payload, dict):
            exchange.fail(
                f"{type(self).__name__}: payload_from={self._payload_from!r} "
                f"вернул не-dict ({type(payload).__name__})"
            )
            return
        await self._dispatch(payload, context, exchange)

    def to_spec(self) -> dict:
        """YAML-spec round-trip."""
        return {
            "entity_create": {
                "entity": self._entity,
                "payload_from": self._payload_from,
                "result_property": self._result_property,
            }
        }


class EntityGetProcessor(_BaseEntityProcessor):
    """Читает сущность через action ``<entity>.get``.

    Args:
        entity: Имя сущности.
        id_from: Выражение извлечения id (default ``body.id``).
        result_property: Имя property для записи объекта.
    """

    _verb = "get"

    def __init__(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        result_property: str = "action_result",
        name: str | None = None,
    ) -> None:
        super().__init__(entity=entity, result_property=result_property, name=name)
        self._id_from = id_from

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        entity_id = _resolve(exchange, self._id_from)
        if entity_id is None:
            exchange.fail(f"{type(self).__name__}: id_from={self._id_from!r} пуст")
            return
        await self._dispatch({"id": entity_id}, context, exchange)

    def to_spec(self) -> dict:
        return {
            "entity_get": {
                "entity": self._entity,
                "id_from": self._id_from,
                "result_property": self._result_property,
            }
        }


class EntityUpdateProcessor(_BaseEntityProcessor):
    """Обновляет сущность через action ``<entity>.update``.

    Args:
        entity: Имя сущности.
        id_from: Выражение извлечения id.
        payload_from: Выражение извлечения payload (default ``body``).
        result_property: Имя property для записи обновлённой сущности.
    """

    _verb = "update"

    def __init__(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        payload_from: str = "body",
        result_property: str = "action_result",
        name: str | None = None,
    ) -> None:
        super().__init__(entity=entity, result_property=result_property, name=name)
        self._id_from = id_from
        self._payload_from = payload_from

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        entity_id = _resolve(exchange, self._id_from)
        payload = _resolve(exchange, self._payload_from)
        if entity_id is None:
            exchange.fail(f"{type(self).__name__}: id_from={self._id_from!r} пуст")
            return
        if not isinstance(payload, dict):
            exchange.fail(
                f"{type(self).__name__}: payload_from={self._payload_from!r} "
                f"вернул не-dict"
            )
            return
        await self._dispatch({"id": entity_id, "data": payload}, context, exchange)

    def to_spec(self) -> dict:
        return {
            "entity_update": {
                "entity": self._entity,
                "id_from": self._id_from,
                "payload_from": self._payload_from,
                "result_property": self._result_property,
            }
        }


class EntityDeleteProcessor(_BaseEntityProcessor):
    """Удаляет сущность через action ``<entity>.delete``.

    Args:
        entity: Имя сущности.
        id_from: Выражение извлечения id.
        result_property: Имя property для записи результата (обычно ``True``/``None``).
    """

    _verb = "delete"

    def __init__(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        result_property: str = "action_result",
        name: str | None = None,
    ) -> None:
        super().__init__(entity=entity, result_property=result_property, name=name)
        self._id_from = id_from

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        entity_id = _resolve(exchange, self._id_from)
        if entity_id is None:
            exchange.fail(f"{type(self).__name__}: id_from={self._id_from!r} пуст")
            return
        await self._dispatch({"id": entity_id}, context, exchange)

    def to_spec(self) -> dict:
        return {
            "entity_delete": {
                "entity": self._entity,
                "id_from": self._id_from,
                "result_property": self._result_property,
            }
        }


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
            "filters": filters if isinstance(filters, dict) else {}
        }
        if page is not None:
            payload["page"] = page
        if size is not None:
            payload["size"] = size
        await self._dispatch(payload, context, exchange)

    def to_spec(self) -> dict:
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
