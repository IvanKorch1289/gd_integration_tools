"""TenantFacade — unified facade для tenant operations (S183 I-4).

Закрывает gap — нет явного facade для multi-tenancy. Extensions и DSL
могут использовать единый entry-point:

- :func:`current()` — get current TenantContext
- :func:`set()` — set tenant context (for request handler)
- :func:`with_tenant()` — async context manager for scoped tenant
- :func:`is_system()` — check if current tenant is system
- :func:`all_tenants()` — list all known tenants (lazy from cache)

Делегирует к :class:`TenantContext` через DI.

Ponytail: thin wrapper, не дублирует логику tenancy.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.tenancy import TenantContext

__all__ = ("TenantFacade", "get_tenant_facade")


class TenantFacade:
    """Unified facade для tenant operations.

    Wraps :class:`TenantContext`, :func:`current_tenant`, :func:`set_tenant`
    через единый entry-point.
    """

    def __init__(self) -> None:
        """Инициализация facade."""

    def current(self) -> TenantContext | None:
        """Получить текущий tenant-контекст.

        Returns:
            Активный канонический :class:`TenantContext` либо ``None``.

        """
        from src.backend.core.tenancy import current_tenant

        return current_tenant()

    def set(self, ctx: TenantContext | None) -> None:
        """Установить текущий tenant-контекст.

        Args:
            ctx: Контекст тенанта (``None`` — снять контекст).

        Raises:
            TypeError: объект не удовлетворяет протоколу tenant-контекста
                (fail-closed, см. ``core.tenancy.set_tenant``).

        """
        from src.backend.core.tenancy import set_tenant

        set_tenant(ctx)

    def is_system(self) -> bool:
        """Check — текущий tenant system?

        Returns:
            True если current_tenant is system tenant.

        """
        ctx = self.current()
        if ctx is None:
            return True

        try:
            from src.backend.core.security.capabilities.tenant import SYSTEM_TENANT_ID

            return ctx.tenant_id == SYSTEM_TENANT_ID
        except (ImportError, AttributeError) as tenant_exc:
            # D-A1-04 fix (cycle 32): narrow exceptions + observability.
            # Bare `except Exception` маскировал security-critical
            # SYSTEM_TENANT_ID import failure → silent permission grant.
            from src.backend.core.logging import get_logger

            get_logger(__name__).warning(
                "tenancy.system_tenant_check.failed", extra={"error": str(tenant_exc)}
            )
            return False

    def tenant_id(self) -> str:
        """Получить tenant_id текущего context.

        Returns:
            tenant_id или ``"_system"`` как fallback.

        """
        ctx = self.current()
        if ctx is None:
            return "_system"
        return ctx.tenant_id

    def principal_id(self) -> str | None:
        """Получить principal_id текущего context."""
        from src.backend.core.tenancy import get_principal_id

        return get_principal_id()

    @asynccontextmanager
    async def with_tenant(
        self, tenant_id: str, principal_id: str | None = None
    ) -> AsyncIterator[TenantContext]:
        """Async context manager для scoped tenant (S193 fix).

        Ставит **канонический** :class:`src.backend.core.tenancy.TenantContext`
        (аудит Z-07): раньше сюда клался :class:`CapabilityTenant` (атрибут
        ``id``, но нет ``tenant_id``), и код ядра, читающий ``ctx.tenant_id``,
        получал ``AttributeError`` → проверка прав уходила в tenant-less
        режим (fail-open).

        Args:
            tenant_id: Tenant ID для scoped context.
            principal_id: Principal (user) ID.

        Yields:
            Установленный :class:`TenantContext` — тот же объект, который
            видят и код ядра, и capability-контур.

        Usage::

            async with facade.with_tenant("tenant_42", principal_id="user_1"):
                # All operations используют tenant_42

        """
        # CapabilityTenant(id, principal) не использовался: контекст теперь
        # единый (core.tenancy.TenantContext) и несёт principal_id.
        # При None principal — fallback на SYSTEM_TENANT_ID ("system code
        # без явного principal").
        from src.backend.core.tenancy import SYSTEM_TENANT_ID, TenantContext, set_tenant

        prev_ctx = self.current()
        new_ctx = TenantContext(
            tenant_id=tenant_id, principal_id=principal_id or SYSTEM_TENANT_ID
        )
        set_tenant(new_ctx)
        try:
            yield new_ctx
        finally:
            set_tenant(prev_ctx)  # Restore previous


@lru_cache(maxsize=1)
def get_tenant_facade() -> TenantFacade:
    """Lazy singleton глобального :class:`TenantFacade`."""
    return TenantFacade()
