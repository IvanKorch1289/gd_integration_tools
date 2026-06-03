"""Unit tests for src.backend.core.interfaces.capability_gateway."""

from __future__ import annotations

from src.backend.core.interfaces.capability_gateway import CapabilityGatewayProtocol


class TestCapabilityGatewayProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            def check(
                self, plugin: str, capability: str, scope: str | None = None
            ) -> None:
                pass

            def declare(self, plugin: str, capabilities: list[object]) -> None:
                pass

            def list_allocated(self, plugin: str) -> tuple[str, ...]:
                return ()

        assert isinstance(Fake(), CapabilityGatewayProtocol)

    def test_missing_method_fails(self) -> None:
        class Bad:
            def check(
                self, plugin: str, capability: str, scope: str | None = None
            ) -> None:
                pass

        assert not isinstance(Bad(), CapabilityGatewayProtocol)
