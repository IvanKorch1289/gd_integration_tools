"""Async-safe correlation context через contextvars.

Хранит correlation_id, request_id, tenant_id — доступны
из любого async-контекста без передачи через аргументы.

Sprint 1 V16: значения дополнительно зеркалируются в
``structlog.contextvars.bind_contextvars``, чтобы попасть в каждое
лог-событие без явного ``logger.bind`` (R-V15-11 audit propagation).
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

import structlog

__all__ = (
    "correlation_id_var",
    "get_correlation_id",
    "get_request_id",
    "get_tenant_id",
    "new_correlation_id",
    "request_id_var",
    "set_correlation_context",
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
