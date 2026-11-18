"""Единый тип tenant-контекста — re-export из :mod:`src.backend.core.tenancy.context`.

Исторически здесь жили :class:`CapabilityTenant` и **второй, несовместимый**
:class:`TenantContext` (с ``principal_id``/``extra``). Из-за двух разных типов
``services.tenancy.TenantFacade.with_tenant()`` клал в tenant-ContextVar
:class:`CapabilityTenant` (у него есть атрибут ``id``, но нет ``tenant_id``),
тогда как код ядра читал ``ctx.tenant_id`` → ``AttributeError``, который
глушился → проверка прав уходила в tenant-less режим (**fail-open**, аудит
Z-07).

Теперь источник правды один — :mod:`src.backend.core.tenancy.context`:
:class:`TenantContext` несёт и ``tenant_id``, и ``principal_id``,
:class:`CapabilityTenant` предоставляет те же значения под алиасами
``tenant_id`` / ``principal_id``. Этот модуль оставлен как backward-compat
фасад для существующих импортов::

    from src.backend.core.security.capabilities.tenant import CapabilityTenant

Проверка согласованности (инвариант единого типа) — в
:meth:`src.backend.core.tenancy.context.TenantContext.to_tenant` и
:meth:`src.backend.core.tenancy.context.CapabilityTenant.to_context`:
``CapabilityTenant.tenant_id == TenantContext.tenant_id``.
"""

from src.backend.core.tenancy.context import (
    SYSTEM_TENANT_ID,
    CapabilityTenant,
    TenantContext,
    TenantContextLike,
    normalize_tenant_context,
)

__all__ = (
    "SYSTEM_TENANT_ID",
    "CapabilityTenant",
    "TenantContext",
    "TenantContextLike",
    "normalize_tenant_context",
)
