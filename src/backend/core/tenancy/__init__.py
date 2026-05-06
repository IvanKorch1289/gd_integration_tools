"""Multi-tenancy — TenantContext + RLS + Redis prefix (G1).

Tenant resolver читает header ``X-Tenant-ID`` или subdomain, устанавливает
``TenantContext.current``. Все нижележащие слои (DB, Redis, logs,
metrics) используют контекст для изоляции.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

__all__ = (
    "TenantContext",
    "current_tenant",
    "set_tenant",
    "tenant_scope",
    "QuotaTracker",
    "QuotaExceeded",
)


@dataclass(slots=True, frozen=True)
class TenantContext:
    tenant_id: str
    plan: str = "free"  # free/basic/pro/enterprise
    region: str = "ru"
    rate_limit: int = 100  # req/min


_current: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


def current_tenant() -> TenantContext | None:
    return _current.get()


def set_tenant(ctx: TenantContext) -> None:
    _current.set(ctx)


class tenant_scope:
    """Контекст-менеджер на время обработки запроса."""

    def __init__(self, ctx: TenantContext) -> None:
        self._ctx = ctx
        self._token = None

    def __enter__(self) -> TenantContext:
        self._token = _current.set(self._ctx)
        return self._ctx

    def __exit__(self, *args) -> None:
        if self._token is not None:
            _current.reset(self._token)


# Re-exports после определения symbols (порядок важен для избежания циклов).
from src.backend.core.tenancy.quotas import QuotaExceeded, QuotaTracker  # noqa: E402
