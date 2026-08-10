"""S175 Phase 2: _BaseEntityProcessor (inline в _legacy.py для простоты).

Shared entity resolution helpers + common params для всех 5 Entity операций.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.types.invocation_command import ActionCommandSchema
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error


class _BaseEntityProcessor(BaseProcessor):
    """Shared base для CRUD-стиля Entity операций.

    Args:
        entity: имя entity (registered в EntityRegistry).
        payload_from: JMESPath expression для извлечения payload из exchange.
        result_property: имя property для записи результата.
        name: имя процессора.
    """

    _verb: ClassVar[str] = ""
    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL

    def __init__(
        self,
        *,
        entity: str,
        payload_from: str | None = None,
        result_property: str | None = None,
        name: str | None = None,
    ) -> None:
        if not entity or "." in entity:
            raise ValueError(f"entity name must be non-empty and contain no dots: {entity!r}")
        super().__init__(name=name or f"entity_{self._verb}:{entity}")
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
        except (ImportError, AttributeError, TypeError, ValueError, jmespath.exceptions.ParseError) as jmespath_exc:
            # cycle-9/D-AUDIT-975: narrow exceptions + observability.
            # ImportError — jmespath missing, AttributeError — jmespath
            # API change, TypeError — wrong body type, ValueError — invalid
            # search syntax, jmespath.exceptions.ParseError — bad query.
            import logging
            logging.getLogger(__name__).debug(
                "entity_legacy.jmespath_search_fallback",
                extra={"error": str(jmespath_exc)},
            )
            return None

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Default no-op — subclasses override."""
        return

    async def _dispatch(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
        exchange: Exchange[Any],
    ) -> Any:
        """Формирует action command, диспетчеризирует, пишет результат в exchange."""
        command = ActionCommandSchema(action=f"{self._entity}.{self._verb}", payload=payload)
        result = await context.action_registry.dispatch(command)
        exchange.set_property(self._result_property, result)
        if result is not None:
            exchange.out_message = exchange.out_message or type(exchange.in_message)()
            exchange.out_message.body = result
        return result
