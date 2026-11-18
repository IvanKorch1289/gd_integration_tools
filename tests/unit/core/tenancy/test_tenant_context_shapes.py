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
"""

from __future__ import annotations

import pytest

from src.backend.core.security.capabilities.tenant import CapabilityTenant
from src.backend.core.tenancy import bind_tenant, get_tenant_id, unbind_tenant

pytestmark = pytest.mark.unit


class TestCapabilityTenantCompatibility:
    """``CapabilityTenant`` читается как tenant-контекст ядра."""

    def test_tenant_id_alias(self) -> None:
        """Алиас ``tenant_id`` совпадает с ``id``."""
        tenant = CapabilityTenant(id="tenant_42", principal="user_1")

        assert tenant.tenant_id == "tenant_42"

    def test_core_tenancy_reads_capability_tenant(self) -> None:
        """``get_tenant_id()`` отдаёт id контекста, установленного фасадом."""
        token = bind_tenant(CapabilityTenant(id="tenant_42", principal="user_1"))  # type: ignore[arg-type]
        try:
            assert get_tenant_id() == "tenant_42"
        finally:
            unbind_tenant(token)

    def test_system_tenant_alias_stays_system(self) -> None:
        """Системный tenant остаётся системным (значение sentinel'а)."""
        tenant = CapabilityTenant(id="_system", principal="core")

        assert tenant.tenant_id == "_system"
        assert tenant.is_system is True
