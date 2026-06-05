"""Unit tests for src.backend.core.interfaces.capability_gateway.

Sprint 36 (V15 GAP, Subagent A): добавлен fake-класс с tenant-aware
методами для проверки расширенного протокола.
"""

from __future__ import annotations

from src.backend.core.interfaces.capability_gateway import CapabilityGatewayProtocol


class _BaseFake:
    """Минимальный fake — только 3 базовых метода."""

    def check(
        self, plugin: str, capability: str, scope: str | None = None
    ) -> None:
        pass

    def declare(self, plugin: str, capabilities: list[object]) -> None:
        pass

    def list_allocated(self, plugin: str) -> tuple[str, ...]:
        return ()


class _TenantAwareFake(_BaseFake):
    """Полный fake с tenant-aware методами (Sprint 36 V15 GAP)."""

    def check_tenant(
        self,
        capability: str,
        tenant: str,
        principal: str,
        scope: str | None = None,
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

    def check(
        self, plugin: str, capability: str, scope: str | None = None
    ) -> None:
        pass


class TestCapabilityGatewayProtocol:
    def test_is_runtime_checkable(self) -> None:
        assert isinstance(_TenantAwareFake(), CapabilityGatewayProtocol)

    def test_minimal_fake_passes_runtime_check(self) -> None:
        # Subagent A: Protocol эволюционировал — добавлены 4 tenant-aware
        # метода. Минимальный fake (_BaseFake) уже **не** удовлетворяет
        # Protocol; тест ниже документирует это поведение.
        assert not isinstance(_BaseFake(), CapabilityGatewayProtocol)
        assert isinstance(_TenantAwareFake(), CapabilityGatewayProtocol)

    def test_missing_method_fails(self) -> None:
        assert not isinstance(_Bad(), CapabilityGatewayProtocol)
