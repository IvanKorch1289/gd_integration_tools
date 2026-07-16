"""S175 Phase 2: EntityCreateProcessor (full implementation).

Split из entity.py godfile.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
    handle_processor_error,
)
from src.backend.dsl.engine.processors.entity._legacy import _BaseEntityProcessor

__all__ = ("EntityCreateProcessor",)


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
        """Resolve payload from exchange, validate dict, dispatch entity creation."""
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
