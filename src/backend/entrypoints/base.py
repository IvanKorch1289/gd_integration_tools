"""Base entrypoint — общий dispatch/error handling для всех протоколов.

IL-CRIT1.5. До этой фазы `BaseEntrypoint.dispatch()` вызывал
`action_handler_registry.dispatch(action, payload)` — но registry
реально принимает единственный аргумент `command: ActionCommandSchema`.
Базовый класс никогда не работал бы корректно. Исправлено:
корректная сборка `ActionCommandSchema` + `meta` (source / correlation_id /
tenant_id) + logging с ref-id.

Унифицированная сущность диспатча используется:
  * REST (`entrypoints/api/v1/*`)
  * gRPC (`grpc_server._dispatch`)
  * GraphQL (`graphql/schema._dispatch_action`)
  * SOAP (`soap/soap_handler._dispatch_via_action`)
  * Webhook / MCP / WebSocket / SSE / Email
  * RabbitMQ / Kafka consumers (через ту же `dispatch_action`)
  * Durable workflow triggers (IL-WF1 в разработке)

Все протоколы вызывают единую `dispatch_action()` — consistent behaviour,
единая точка добавления cross-cutting concerns (tracing, audit, quota,
tenant propagation).
"""

from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from src.backend.dsl.commands.registry import action_handler_registry
from src.backend.schemas.invocation import ActionCommandSchema

__all__ = ("BaseEntrypoint", "dispatch_action")

logger = logging.getLogger(__name__)


async def dispatch_action(
    *,
    action: str,
    payload: dict[str, Any] | None = None,
    source: str,
    correlation_id: str | None = None,
    tenant_id: str | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> Any:
    """Единый фасад-диспатчер для любого entrypoint / consumer / workflow.

    Собирает `ActionCommandSchema` с заполненным `meta` и делегирует в
    `action_handler_registry.dispatch()`. Единое место для:
      * генерации correlation_id (если не передан сверху),
      * добавления `source` (rest/grpc/graphql/soap/rabbit/kafka/workflow),
      * propagation `tenant_id` в Exchange → OTEL baggage,
      * latency-logging для observability.

    Raises ту же ошибку, что и registry (включая KeyError,
    ValidationError). Вызывающий entrypoint отвечает за protocol-specific
    formatting ошибок.
    """
    cid = correlation_id or uuid.uuid4().hex[:12]
    meta: dict[str, Any] = {"source": source, "correlation_id": cid}
    if tenant_id is not None:
        meta["tenant_id"] = tenant_id
    if extra_meta:
        meta.update(extra_meta)

    command = ActionCommandSchema(action=action, payload=payload or {}, meta=meta)

    start = time.monotonic()
    try:
        result = await action_handler_registry.dispatch(command)
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.debug("%s dispatch %s [ref=%s]: %.1fms", source, action, cid, elapsed_ms)
        return result
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.error(
            "%s dispatch %s failed [ref=%s]: %s (%.1fms)",
            source,
            action,
            cid,
            exc,
            elapsed_ms,
        )
        raise


class BaseEntrypoint(ABC):
    """Абстрактный базовый класс для всех entrypoints.

    Унифицирует:
    - dispatch через ActionHandlerRegistry
    - error handling (единый формат ошибок)
    - metrics collection (latency, success/error count)
    - correlation ID propagation
    """

    protocol: str = "unknown"

    async def dispatch(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        tenant_id: str | None = None,
        extra_meta: dict[str, Any] | None = None,
    ) -> Any:
        """Dispatch action через общий `dispatch_action()`.

        Используется классами-наследниками (REST / gRPC / GraphQL / SOAP).
        `protocol` берётся из ClassVar (каждый entrypoint задаёт свой).
        """
        return await dispatch_action(
            action=action,
            payload=payload,
            source=self.protocol,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            extra_meta=extra_meta,
        )

    def serialize_result(self, result: Any) -> Any:
        """Сериализует результат для конкретного протокола. Override в подклассах."""
        return result

    def format_error(self, exc: Exception) -> dict[str, Any]:
        """Форматирует ошибку для конкретного протокола."""
        return {
            "error": exc.__class__.__name__,
            "message": str(exc),
            "protocol": self.protocol,
        }

    @abstractmethod
    async def handle(self, *args: Any, **kwargs: Any) -> Any:
        """Точка входа для обработки запроса конкретным протоколом."""
        ...
