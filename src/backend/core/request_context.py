"""ADR-NEW-3 (Sprint 17): унифицированный :class:`RequestContext`.

Контекст:
    До S17 поля запроса (``correlation_id``, ``request_id``, ``trace_id``,
    ``tenant_id``, ``auth``) хранились разрозненно:

    * ``asgi_correlation_id`` ContextVar для correlation_id;
    * ``request.state.tenant_id`` + ``TenantMiddleware`` ContextVar;
    * ``request.state.request_id`` + ``RequestIDMiddleware``;
    * ``request.state.auth`` (от ``AuthRequiredMiddleware``);
    * ``trace_id`` / ``span_id`` доступны только через OTel API.

    Это приводило к 30+ callsites чтения разрозненных полей в audit /
    DSL processors / outbound HTTP, дубликации propagation-логики и
    риску desync (ASGI-stage A знает correlation, stage B не знает).

Решение:
    :class:`RequestContext` — frozen dataclass с единым набором полей,
    устанавливается единожды :class:`RequestContextMiddleware` в начале
    цепочки. Чтение через :meth:`RequestContext.current()` из любого
    места (audit, DSL processor, outbound HTTP client).

API:
    .. code-block:: python

        ctx = RequestContext.current()
        if ctx is not None:
            structlog.contextvars.bind_contextvars(
                correlation_id=ctx.correlation_id,
                tenant_id=ctx.tenant_id,
            )

Backward-compat:
    ``request.state.correlation_id`` остаётся, но deprecated — после
    миграции callsites в отдельной wave (`[wave:s17/k3-w1-migrate-callsites]`)
    будет удалён.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

__all__ = (
    "REQUEST_CONTEXT_VAR",
    "RequestContext",
    "bind_request_context",
    "clear_request_context",
)


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Унифицированный snapshot контекста запроса.

    Attributes:
        correlation_id: Сквозной идентификатор cross-service
            (``X-Correlation-ID`` header).
        request_id: Уникальный идентификатор внутри сервиса
            (``X-Request-ID`` header).
        trace_id: OTel trace_id (если активен span).
        span_id: OTel span_id (если активен span).
        tenant_id: Tenant идентификатор (``X-Tenant-ID`` header).
        auth: Произвольный auth-context (передаётся как dict).
        client_id: Идентификатор клиента (API key / mTLS CN).
        method: HTTP метод (``GET`` / ``POST`` / ...).
        path: Path запроса (без query).
    """

    correlation_id: str
    request_id: str
    method: str
    path: str
    trace_id: str | None = None
    span_id: str | None = None
    tenant_id: str | None = None
    auth: dict[str, Any] | None = None
    client_id: str | None = None

    @classmethod
    def current(cls) -> "RequestContext | None":
        """Возвращает текущий RequestContext или ``None``."""
        return REQUEST_CONTEXT_VAR.get(None)


REQUEST_CONTEXT_VAR: ContextVar[RequestContext | None] = ContextVar(
    "gd_request_context", default=None
)
"""ContextVar для глобального доступа к :class:`RequestContext`."""


def bind_request_context(ctx: RequestContext) -> object:
    """Привязать ``RequestContext`` к текущему async-контексту.

    Args:
        ctx: Снимок контекста запроса.

    Returns:
        Token для :func:`clear_request_context`.
    """
    return REQUEST_CONTEXT_VAR.set(ctx)


def clear_request_context(token: object) -> None:
    """Сбросить ``RequestContext`` (вызывается в finally).

    Args:
        token: Token, возвращённый :func:`bind_request_context`.
    """
    REQUEST_CONTEXT_VAR.reset(token)  
