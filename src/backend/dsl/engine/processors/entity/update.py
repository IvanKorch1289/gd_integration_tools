"""S175 Phase 2: EntityUpdateProcessor (full implementation).

Split из entity.py godfile.
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.entity._legacy import _BaseEntityProcessor

from ._resolve import _resolve

__all__ = ("EntityUpdateProcessor",)


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
        """Resolve id + payload, dispatch entity update."""
        entity_id = _resolve(exchange, self._id_from)
        payload = _resolve(exchange, self._payload_from)
        if entity_id is None:
            exchange.fail(f"{type(self).__name__}: id_from={self._id_from!r} пуст")
            return
        if not isinstance(payload, dict):
            exchange.fail(
                f"{type(self).__name__}: payload_from={self._payload_from!r} "
                f"вернул не-dict",
            )
            return
        await self._dispatch({"id": entity_id, "data": payload}, context, exchange)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует entity_update конфиг в JSON-Schema spec."""
        return {
            "entity_update": {
                "entity": self._entity,
                "id_from": self._id_from,
                "payload_from": self._payload_from,
                "result_property": self._result_property,
            },
        }
