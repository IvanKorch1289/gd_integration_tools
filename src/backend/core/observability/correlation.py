"""Canonical correlation context — pure stdlib (contextvars + structlog).

Хранит correlation_id, request_id, tenant_id — доступны
из любого async-контекста без передачи через аргументами.

R-V15-11: значения зеркалируются в structlog.contextvars.bind_contextvars,
чтобы попадать в каждое лог-событие без явного logger.bind.

Phase 1a (infra analysis backlog): canonical class moved here.
Бывший infra-файл стал thin re-export shim для backward-compat.
Новый код должен импортировать из этого модуля.
"""

from __future__ import annotations

import contextlib
import uuid
from contextvars import ContextVar
from typing import Any

import structlog

__all__ = (
    "correlation_id_var",
    "get_correlation_id",
    "get_request_id",
    "get_tenant_id",
    "new_correlation_id",
    "request_id_var",
    "set_correlation_context",
    "set_correlation_id",
    "start_span",
    "tenant_id_var",
)

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="")


def set_correlation_context(
    correlation_id: str | None = None,
    request_id: str | None = None,
    tenant_id: str | None = None,
) -> None:
    """Set correlation context variables for logging.

    Args:
        correlation_id: Optional correlation ID.
        request_id: Optional request ID.
        tenant_id: Optional tenant ID.
    """
    bind: dict[str, str] = {}
    if correlation_id:
        correlation_id_var.set(correlation_id)
        bind["correlation_id"] = correlation_id
    if request_id:
        request_id_var.set(request_id)
        bind["request_id"] = request_id
    if tenant_id:
        tenant_id_var.set(tenant_id)
        bind["tenant_id"] = tenant_id
    if bind:
        structlog.contextvars.bind_contextvars(**bind)


def get_correlation_id() -> str:
    """Get current correlation ID from context.

    Returns:
        Correlation ID string.
    """
    return correlation_id_var.get()


def get_request_id() -> str:
    """Get current request ID from context.

    Returns:
        Request ID string.
    """
    return request_id_var.get()


def get_tenant_id() -> str:
    """Get current tenant ID from context.

    Returns:
        Tenant ID string.
    """
    return tenant_id_var.get()


def new_correlation_id() -> str:
    """Generate and set a new correlation ID.

    Returns:
        New correlation ID string.
    """
    cid = uuid.uuid4().hex[:16]
    correlation_id_var.set(cid)
    return cid


def set_correlation_id(correlation_id: str) -> None:
    """Установить correlation_id (alias для :func:`set_correlation_context`).

    Round 5 Sprint 5.2: compat-shim для callers (например,
    :class:`services.observability.facade.ObservabilityFacade.set_correlation_id`),
    которые хотят установить только correlation_id без request_id/tenant_id.
    Делегирует в :func:`set_correlation_context` с единственным параметром.

    Args:
        correlation_id: Correlation ID (UUID либо hex-string).
    """
    set_correlation_context(correlation_id=correlation_id)


@contextlib.contextmanager
def start_span(name: str, attributes: dict[str, Any] | None = None) -> Any:
    """No-op tracing span context manager (Round 5 Sprint 5.2 compat-shim).

    Изначально facade ожидал реальный OTEL-совместимый ``start_span``,
    но проект пока не подключил OTEL SDK (carryover, см. ADR-NEW-21).
    До тех пор возвращаем no-op context manager, который всегда
    yields ``None``. При появлении OTEL SDK этот shim будет заменён
    на ``opentelemetry.trace.get_tracer(__name__).start_as_current_span``.

    Args:
        name: Имя span (например, ``"process_order"``).
        attributes: Span attributes (key-value).

    Yields:
        ``None`` (placeholder, real span появится с OTEL).
    """
    yield None
