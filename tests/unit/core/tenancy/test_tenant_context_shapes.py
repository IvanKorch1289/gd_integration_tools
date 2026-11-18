"""Совместимость tenant-контекстов: ``CapabilityTenant`` ↔ ``core.tenancy``.

Регрессия: ``services.tenancy.TenantFacade.with_tenant()`` кладёт в
tenant-ContextVar объект :class:`CapabilityTenant` (у него атрибут ``id``),
а ``core.tenancy`` / ORM-фильтр / capability-гейт читают ``ctx.tenant_id``.
Без алиаса чтение падало с ``AttributeError``:

* ``core.tenancy.get_tenant_id()`` → ``AttributeError``;
* ``sqlalchemy_filter`` → ``AttributeError`` на ``ctx.tenant_id``;
* ``connector_auth.require_capability`` → ``AttributeError`` **поглощался**
  (``except (ImportError, AttributeError, RuntimeError)``) → capability-проверка
  уходила в tenant-less режим (fail-open).

Алиас ``CapabilityTenant.tenant_id`` убирает расхождение в core.

Волна 35 (Z-07, план P1-4/P1-5) дополнительно: канонический тип контекста —
``core.tenancy.TenantContext`` (несёт ``tenant_id`` **и** ``principal_id``),
а ``CapabilityTenant`` отдаёт те же значения под алиасами ``tenant_id`` /
``principal_id`` — оба типа удовлетворяют протоколу ``TenantContextLike``.
"""

from __future__ import annotations

import pytest

from src.backend.core.security.capabilities.tenant import CapabilityTenant
from src.backend.core.tenancy import (
    TenantContext,
    TenantContextLike,
    bind_tenant,
    current_tenant,
    get_principal_id,
    get_tenant_id,
    unbind_tenant,
)

pytestmark = pytest.mark.unit


class TestCapabilityTenantCompatibility:
    """``CapabilityTenant`` читается как tenant-контекст ядра."""

    def test_tenant_id_alias(self) -> None:
        """Алиас ``tenant_id`` совпадает с ``id``."""
        tenant = CapabilityTenant(id="tenant_42", principal="user_1")

        assert tenant.tenant_id == "tenant_42"

    def test_principal_id_alias(self) -> None:
        """Алиас ``principal_id`` совпадает с ``principal``."""
        tenant = CapabilityTenant(id="tenant_42", principal="user_1")

        assert tenant.principal_id == "user_1"

    def test_satisfies_tenant_context_protocol(self) -> None:
        """``CapabilityTenant`` удовлетворяет протоколу tenant-контекста."""
        tenant = CapabilityTenant(id="tenant_42", principal="user_1")

        assert isinstance(tenant, TenantContextLike)

    def test_core_tenancy_reads_capability_tenant(self) -> None:
        """``get_tenant_id()`` отдаёт id контекста, установленного фасадом.

        ``CapabilityTenant`` приводится к каноническому ``TenantContext``
        (значения те же) — в ContextVar лежит единый тип.
        """
        token = bind_tenant(CapabilityTenant(id="tenant_42", principal="user_1"))
        try:
            assert get_tenant_id() == "tenant_42"
            assert get_principal_id() == "user_1"
            assert isinstance(current_tenant(), TenantContext)
        finally:
            unbind_tenant(token)

    def test_system_tenant_alias_stays_system(self) -> None:
        """Системный tenant остаётся системным (значение sentinel'а)."""
        tenant = CapabilityTenant(id="_system", principal="core")

        assert tenant.tenant_id == "_system"
        assert tenant.is_system is True
