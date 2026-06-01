"""Unit-тесты :class:`AuthorizationGateway` (ADR-NEW-1 + ADR-NEW-4, Sprint 17).

Покрытие:
    * happy-path: CapabilityGate allow → policy allow → decision.allowed
    * deny через CapabilityGate (CapabilityDeniedError);
    * deny через дополнительную async policy;
    * audit-event ``authorization.decision`` эмитится один раз с
      полным reason-chain и единым correlation_id;
    * feature-flag default-OFF → allow без проверок;
    * isinstance(CapabilityGate(), CapabilityGatewayProtocol) — runtime
      проверка реализации (ADR-NEW-4).
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.core.interfaces.capability_gateway import CapabilityGatewayProtocol
from src.backend.core.security.authorization_gateway import (
    AuthorizationGateway,
    AuthorizationReason,
)
from src.backend.core.security.capabilities import (
    CapabilityRef,
    build_default_vocabulary,
)
from src.backend.core.security.capabilities.gate import CapabilityGate


@pytest.fixture(autouse=True)
def _enable_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """Все тесты по умолчанию работают с включённым фасадом."""
    monkeypatch.setattr(feature_flags, "authz_gateway_enabled", True)


def _build_gate_with_declaration(
    plugin: str = "p1",
    capability_name: str = "db.read",
    scope: str = "users",
) -> CapabilityGate:
    """Возвращает CapabilityGate с одной декларацией."""
    gate = CapabilityGate(vocabulary=build_default_vocabulary())
    gate.declare(plugin, (CapabilityRef(name=capability_name, scope=scope),))
    return gate


class TestProtocolConformance:
    """ADR-NEW-4: CapabilityGate реализует CapabilityGatewayProtocol."""

    def test_capability_gate_is_protocol_instance(self) -> None:
        gate = CapabilityGate()
        assert isinstance(gate, CapabilityGatewayProtocol)

    def test_list_allocated_returns_names_only(self) -> None:
        gate = _build_gate_with_declaration()
        assert gate.list_allocated("p1") == ("db.read",)
        assert gate.list_allocated("absent_plugin") == ()


class TestAuthorizeHappyPath:
    """Happy-path: capability allow + policy allow → decision.allowed."""

    async def test_capability_only_allow(self) -> None:
        gateway = AuthorizationGateway(
            capability_gateway=_build_gate_with_declaration(),
        )
        decision = await gateway.authorize(
            principal="p1",
            resource="db.read",
            action="check",
            context={"scope": "users"},
        )
        assert decision.allowed is True
        sources = [r.source for r in decision.reasons]
        assert sources == ["capability_gateway"]

    async def test_capability_plus_async_policy_allow(self) -> None:
        async def _allow_policy(
            principal: str, resource: str, action: str, ctx: dict[str, Any]
        ) -> AuthorizationReason:
            return AuthorizationReason(source="my_policy", outcome="allow")

        gateway = AuthorizationGateway(
            capability_gateway=_build_gate_with_declaration(),
            policies=(_allow_policy,),
        )
        decision = await gateway.authorize(
            principal="p1",
            resource="db.read",
            action="check",
            context={"scope": "users"},
        )
        assert decision.allowed is True
        sources = [r.source for r in decision.reasons]
        assert sources == ["capability_gateway", "my_policy"]


class TestAuthorizeDenyPaths:
    """Deny paths: capability denied / policy denied / exception."""

    async def test_capability_denied(self) -> None:
        # Plugin без декларации → capability check raise → deny
        gate = CapabilityGate(vocabulary=build_default_vocabulary())
        gateway = AuthorizationGateway(capability_gateway=gate)
        decision = await gateway.authorize(
            principal="absent_plugin",
            resource="db.read",
            action="check",
            context={"scope": "users"},
        )
        assert decision.allowed is False
        assert decision.reasons[-1].source == "capability_gateway"
        assert decision.reasons[-1].outcome == "deny"

    async def test_policy_denied_short_circuits(self) -> None:
        called: list[str] = []

        async def _allow_policy(
            principal: str, resource: str, action: str, ctx: dict[str, Any]
        ) -> AuthorizationReason:
            called.append("first")
            return AuthorizationReason(source="first", outcome="allow")

        async def _deny_policy(
            principal: str, resource: str, action: str, ctx: dict[str, Any]
        ) -> AuthorizationReason:
            called.append("deny")
            return AuthorizationReason(
                source="rbac", outcome="deny", detail="role not granted"
            )

        async def _never_called(
            principal: str, resource: str, action: str, ctx: dict[str, Any]
        ) -> AuthorizationReason:
            called.append("never")
            return AuthorizationReason(source="never", outcome="allow")

        gateway = AuthorizationGateway(
            capability_gateway=_build_gate_with_declaration(),
            policies=(_allow_policy, _deny_policy, _never_called),
        )
        decision = await gateway.authorize(
            principal="p1",
            resource="db.read",
            action="check",
            context={"scope": "users"},
        )
        assert decision.allowed is False
        assert called == ["first", "deny"]  # third policy skipped
        assert decision.reasons[-1].outcome == "deny"


class TestAuditAndCorrelation:
    """Audit-event и correlation_id propagation."""

    async def test_audit_event_emitted_on_allow(self) -> None:
        events: list[dict[str, Any]] = []
        gateway = AuthorizationGateway(
            capability_gateway=_build_gate_with_declaration(),
            audit_callback=events.append,
        )
        decision = await gateway.authorize(
            principal="p1",
            resource="db.read",
            action="check",
            context={"scope": "users", "correlation_id": "fixed-cid-42"},
        )
        assert decision.correlation_id == "fixed-cid-42"
        assert len(events) == 1
        e = events[0]
        assert e["event"] == "authorization.decision"
        assert e["outcome"] == "allow"
        assert e["correlation_id"] == "fixed-cid-42"
        assert e["principal"] == "p1"

    async def test_audit_event_emitted_on_deny(self) -> None:
        events: list[dict[str, Any]] = []
        gate = CapabilityGate(vocabulary=build_default_vocabulary())
        gateway = AuthorizationGateway(
            capability_gateway=gate,
            audit_callback=events.append,
        )
        decision = await gateway.authorize(
            principal="absent_plugin",
            resource="db.read",
            action="check",
        )
        assert decision.allowed is False
        assert events[-1]["outcome"] == "deny"

    async def test_correlation_id_generated_when_absent(self) -> None:
        gateway = AuthorizationGateway(
            capability_gateway=_build_gate_with_declaration(),
        )
        d1 = await gateway.authorize(
            principal="p1",
            resource="db.read",
            action="check",
            context={"scope": "users"},
        )
        d2 = await gateway.authorize(
            principal="p1",
            resource="db.read",
            action="check",
            context={"scope": "users"},
        )
        assert d1.correlation_id != d2.correlation_id
        assert len(d1.correlation_id) >= 8


class TestFeatureFlagGate:
    """default-OFF → allow без проверок (плавная миграция)."""

    async def test_disabled_returns_allow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "authz_gateway_enabled", False)
        gate = CapabilityGate(vocabulary=build_default_vocabulary())
        # Без декларации — нормально CapabilityGate denied, но flag OFF
        gateway = AuthorizationGateway(capability_gateway=gate)
        decision = await gateway.authorize(
            principal="absent_plugin",
            resource="db.read",
            action="check",
        )
        assert decision.allowed is True
        assert decision.reasons[0].source == "feature_flag"
        assert decision.reasons[0].detail == "authz_gateway_enabled=False"
