"""Инвариант: системный tenant-id определён ровно в одном месте.

Значение ``"_system"`` дублировалось в ``core.tenancy`` и
``core.security.capabilities.tenant``: расхождение значений тихо ломало
capability-гейт (системный scope переставал совпадать). Канон —
:data:`src.backend.core.tenancy.context.SYSTEM_TENANT_ID`, остальные
модули только ре-экспортируют его (backward compat).
"""

from __future__ import annotations

import pytest

from src.backend.core.security.capabilities import tenant as capabilities_tenant
from src.backend.core.tenancy import SYSTEM_TENANT_ID, context


@pytest.mark.unit
class TestSystemTenantConstant:
    """Единая константа системного tenant'а."""

    def test_value_is_canonical(self) -> None:
        """Значение константы — ``"_system"``."""
        assert context.SYSTEM_TENANT_ID == "_system"
        assert SYSTEM_TENANT_ID == context.SYSTEM_TENANT_ID

    def test_core_tenancy_reexports_canonical_constant(self) -> None:
        """``core.tenancy`` ре-экспортирует каноническую константу (без копии)."""
        assert SYSTEM_TENANT_ID is context.SYSTEM_TENANT_ID

    def test_capabilities_tenant_reexports_canonical_constant(self) -> None:
        """``capabilities.tenant`` ре-экспортирует каноническую константу."""
        assert capabilities_tenant.SYSTEM_TENANT_ID is context.SYSTEM_TENANT_ID

    def test_system_scope_recognised(self) -> None:
        """Системный tenant-id распознаётся как системный scope."""
        tenant = capabilities_tenant.CapabilityTenant(
            id=context.SYSTEM_TENANT_ID, principal="core"
        )
        assert tenant.is_system is True
