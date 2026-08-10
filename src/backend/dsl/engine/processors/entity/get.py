"""S175 Phase 2: EntityGetProcessor (full implementation).

Split из entity.py godfile.
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.entity._legacy import _BaseEntityProcessor
from src.backend.dsl.engine.processors.entity._resolve import _resolve

__all__ = ("EntityGetProcessor",)


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
        """Resolve entity id, dispatch get query, set result property."""
        entity_id = _resolve(exchange, self._id_from)
        if entity_id is None:
            exchange.fail(f"{type(self).__name__}: id_from={self._id_from!r} пуст")
            return
        await self._dispatch({"id": entity_id}, context, exchange)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует entity_get конфиг в JSON-Schema spec."""
        return {
            "entity_get": {
                "entity": self._entity,
                "id_from": self._id_from,
                "result_property": self._result_property,
            },
        }
