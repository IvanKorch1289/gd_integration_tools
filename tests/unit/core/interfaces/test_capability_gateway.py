"""Unit tests for src.backend.core.interfaces.capability_gateway.

Sprint 36 (V15 GAP, Subagent A): добавлен fake-класс с tenant-aware
методами для проверки расширенного протокола.

Sprint 37.X: Protocol разделён на базовый ``CapabilityGatewayProtocol``
(3 метода) и ``TenantAwareCapabilityGatewayProtocol`` (+4 tenant-aware
метода). Тесты отражают новую иерархию.
"""

from __future__ import annotations

from src.backend.core.interfaces.capability_gateway import (
    CapabilityGatewayProtocol,
    TenantAwareCapabilityGatewayProtocol,
)


class _BaseFake:
    """Минимальный fake — только 3 базовых метода."""

    def check(self, plugin: str, capability: str, scope: str | None = None) -> None:
        pass

    def declare(self, plugin: str, capabilities: list[object]) -> None:
        pass

    def list_allocated(self, plugin: str) -> tuple[str, ...]:
        return ()


class _TenantAwareFake(_BaseFake):
    """Полный fake с tenant-aware методами (Sprint 36 V15 GAP)."""

    def check_tenant(
        self, capability: str, tenant: str, principal: str, scope: str | None = None
    ) -> bool:
        return True

    def declare_tenant(self, capability: object, tenant: str, principal: str) -> None:
        pass

    def revoke_tenant(self, capability: str, tenant: str) -> None:
        pass

    def list_allocated_tenant(self, tenant: str) -> tuple[object, ...]:
        return ()


class _Bad:
    """Без метода ``declare`` — не удовлетворяет Protocol."""

    def check(self, plugin: str, capability: str, scope: str | None = None) -> None:
        pass


class TestCapabilityGatewayProtocol:
    def test_is_runtime_checkable(self) -> None:
        assert isinstance(_BaseFake(), CapabilityGatewayProtocol)
        assert isinstance(_TenantAwareFake(), CapabilityGatewayProtocol)

    def test_minimal_fake_passes_runtime_check(self) -> None:
        # Sprint 37.X: базовый Protocol требует только 3 метода.
        assert isinstance(_BaseFake(), CapabilityGatewayProtocol)

    def test_tenant_aware_protocol_requires_extra_methods(self) -> None:
        # Базовый fake без tenant-aware методов не удовлетворяет
        # расширенному Protocol'у.
        assert not isinstance(_BaseFake(), TenantAwareCapabilityGatewayProtocol)
        assert isinstance(_TenantAwareFake(), TenantAwareCapabilityGatewayProtocol)

    def test_missing_method_fails(self) -> None:
        assert not isinstance(_Bad(), CapabilityGatewayProtocol)
