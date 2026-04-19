"""Async-safe correlation context через contextvars.

Хранит correlation_id, request_id, tenant_id — доступны
из любого async-контекста без передачи через аргументы.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

__all__ = (
    "correlation_id_var",
    "request_id_var",
    "tenant_id_var",
    "set_correlation_context",
    "get_correlation_id",
    "get_request_id",
    "get_tenant_id",
    "new_correlation_id",
)

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="")


def set_correlation_context(
    correlation_id: str | None = None,
    request_id: str | None = None,
    tenant_id: str | None = None,
) -> None:
    if correlation_id:
        correlation_id_var.set(correlation_id)
    if request_id:
        request_id_var.set(request_id)
    if tenant_id:
        tenant_id_var.set(tenant_id)


def get_correlation_id() -> str:
    return correlation_id_var.get()


def get_request_id() -> str:
    return request_id_var.get()


def get_tenant_id() -> str:
    return tenant_id_var.get()


def new_correlation_id() -> str:
    cid = uuid.uuid4().hex[:16]
    correlation_id_var.set(cid)
    return cid
