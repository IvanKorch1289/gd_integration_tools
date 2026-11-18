"""Regression-тесты для TenantFacade.with_tenant kwargs (cycle-4/D-AUDIT-100).

Закрывает T-08 (services:SERV-P0-001 + business-logic:BL-P1-002): CapabilityTenant
принимает ``(id, principal)``, а НЕ ``(tenant_id, principal_id)``. До фикса
каждый вызов ``with_tenant`` падал с ``TypeError``.

Волна 35 (аудит Z-07): контекст в tenant-ContextVar — **единый** тип
``core.tenancy.TenantContext`` (несёт ``tenant_id`` **и** ``principal_id``),
а не ``CapabilityTenant``. Поэтому проверки ниже смотрят на канонические
поля ``tenant_id`` / ``principal_id``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.core.tenancy import TenantContext
from src.backend.services.tenancy.facade import TenantFacade


class TestTenantFacadeKwargs:
    """Regression на kwargs re-fix."""

    @pytest.mark.asyncio
    async def test_with_tenant_accepts_principal_id_kwarg(self) -> None:
        """cycle-4/D-AUDIT-100: ``with_tenant(tenant_id=..., principal_id=...)`` работает.

        До фикса: ``CapabilityTenant(tenant_id=..., principal_id=...)`` → TypeError.
        После: канонический ``TenantContext(tenant_id=..., principal_id=...)``.
        """
        facade = TenantFacade()
        with (
            patch("src.backend.core.tenancy.current_tenant", return_value=None),
            patch("src.backend.core.tenancy.set_tenant") as mock_set,
        ):
            async with facade.with_tenant(tenant_id="t-001", principal_id="p-007"):
                # set_tenant должен быть вызван с каноническим TenantContext.
                assert mock_set.called
                new_ctx = mock_set.call_args_list[0].args[0]
                assert isinstance(new_ctx, TenantContext)
                assert new_ctx.tenant_id == "t-001"
                assert new_ctx.principal_id == "p-007"

    @pytest.mark.asyncio
    async def test_with_tenant_without_principal_uses_system_fallback(self) -> None:
        """Без ``principal_id`` — fallback на SYSTEM_TENANT_ID для principal."""
        facade = TenantFacade()
        with (
            patch("src.backend.core.tenancy.current_tenant", return_value=None),
            patch("src.backend.core.tenancy.set_tenant") as mock_set,
        ):
            async with facade.with_tenant("tenant_42"):
                new_ctx = mock_set.call_args_list[0].args[0]
                assert new_ctx.tenant_id == "tenant_42"
                # principal fallback на SYSTEM_TENANT_ID ("_system")
                assert new_ctx.principal_id == "_system"
