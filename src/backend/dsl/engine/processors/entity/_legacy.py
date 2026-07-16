"""S175 Phase 2: _BaseEntityProcessor (inline в _legacy.py для простоты).

Shared entity resolution helpers + common params для всех 5 Entity операций.
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


class _BaseEntityProcessor(BaseProcessor):
    """Shared base для CRUD-стиля Entity операций.

    Args:
        entity: имя entity (registered в EntityRegistry).
        payload_from: JMESPath expression для извлечения payload из exchange.
        result_property: имя property для записи результата.
        name: имя процессора.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL

    def __init__(
        self,
        *,
        entity: str,
        payload_from: str | None = None,
        result_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"entity_base_{entity}")
        self._entity = entity
        self._payload_from = payload_from
        self._result_property = result_property or f"{entity}_result"

    def _resolve_payload(self, exchange: Exchange[Any]) -> Any:
        """Извлечь payload через JMESPath или вернуть body."""
        if self._payload_from is None:
            return exchange.in_message.body
        try:
            import jmespath
            return jmespath.search(self._payload_from, exchange.in_message.body)
        except Exception:
            return None

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Default no-op — subclasses override."""
        return None
