"""DSL processor ``integration_send`` (S203 W4).

Capability-gated отправка payload через :class:`IntegrationFacade`.::

    - integration_send:
        sink_id: alerts.http
        payload_from: body
        result_property: send_result
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


@processor(
    "integration_send",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {
            "sink_id": {"type": "string"},
            "payload_from": {"type": "string"},
            "result_property": {"type": "string"},
        },
        "required": ["sink_id"],
    },
    capabilities=("sink.send.*",),  # per-kind проверяется в facade
    meta={"tier": 2, "category": "infra"},
)
class IntegrationSendProcessor(BaseProcessor):
    """``integration_send(sink_id, ...)`` — capability-gated sink publish."""

    def __init__(
        self,
        sink_id: str,
        *,
        payload_from: str = "body",
        result_property: str = "integration_send_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"integration_send:{sink_id}")
        self._sink_id = sink_id
        self._payload_from = payload_from
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Извлекает payload и публикует через IntegrationFacade."""
        from src.backend.services.integrations.facade import (
            get_integration_facade,
        )

        # Извлечение payload: "body" → in_message.body; "body.<field>" → field;
        # "properties.<name>" → exchange.properties[name].
        payload = self._extract_payload(exchange)
        # Tenant из exchange, если есть (некоторые extensions проставляют TenantContext).
        tenant_id = (
            exchange.properties.get("tenant_id") if exchange.properties else None
        )

        facade = get_integration_facade()
        try:
            result = await facade.send_to_sink(
                self._sink_id, payload, tenant_id=tenant_id
            )
            exchange.set_property(
                self._result_property,
                {"ok": result.ok, "external_id": result.external_id, **result.details},
            )
        except Exception as exc:
            exchange.set_property(
                self._result_property,
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
            )

    def _extract_payload(self, exchange: Any) -> Any:
        """Простой extractor: body | body.<field> | properties.<name>."""
        src = self._payload_from
        if src == "body":
            return exchange.in_message.body
        if src.startswith("body."):
            field = src[len("body."):]
            body = exchange.in_message.body
            if isinstance(body, dict):
                return body.get(field)
            return getattr(body, field, None)
        if src.startswith("properties."):
            name = src[len("properties."):]
            return exchange.properties.get(name) if exchange.properties else None
        return exchange.in_message.body