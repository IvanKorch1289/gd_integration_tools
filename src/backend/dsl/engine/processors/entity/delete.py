"""S175 Phase 2: EntityDeleteProcessor (full implementation).

Split из entity.py godfile.
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.entity._legacy import _BaseEntityProcessor
from src.backend.dsl.engine.processors.entity._resolve import _resolve

__all__ = ("EntityDeleteProcessor",)


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
        """Resolve entity id, dispatch delete query."""
        entity_id = _resolve(exchange, self._id_from)
        if entity_id is None:
            exchange.fail(f"{type(self).__name__}: id_from={self._id_from!r} пуст")
            return
        await self._dispatch({"id": entity_id}, context, exchange)

    def to_spec(self) -> dict:
        """Сериализует entity_delete конфиг в JSON-Schema spec."""
        return {
            "entity_delete": {
                "entity": self._entity,
                "id_from": self._id_from,
                "result_property": self._result_property,
            }
        }
