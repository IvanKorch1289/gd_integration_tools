"""Unit-тесты :func:`AuthorizationGateway.casbin_step` / `opa_step` (S18 W3).

Покрытие (S-L8-1, S-L8-2 smoke):
    * casbin_step: allow → AuthorizationReason(source="casbin", outcome="allow")
    * casbin_step: deny → outcome="deny" + detail "casbin_enforce_denied"
    * opa_step: feature-flag OFF → no-op allow
    * opa_step: ON + allow → outcome="allow"
    * opa_step: ON + deny → outcome="deny" + reasons-detail
    * Combined chain test: capability → casbin → opa, short-circuit на casbin deny
      пропускает opa (reason-chain ordering verified).
"""

# ruff: noqa: S101

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.core.security.authorization_gateway import AuthorizationGateway
from src.backend.core.security.capabilities import (
    CapabilityRef,
    build_default_vocabulary,
)
from src.backend.core.security.capabilities.gate import CapabilityGate

# ----------------------------- shared fixtures ------------------------------


@pytest.fixture(autouse=True)
def _enable_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """Все тесты по умолчанию работают с включённым фасадом."""
    monkeypatch.setattr(feature_flags, "authz_gateway_enabled", True)


def _build_gate() -> CapabilityGate:
    """CapabilityGate с одной декларацией db.read/users для plugin p1."""
    gate = CapabilityGate(vocabulary=build_default_vocabulary())
    gate.declare("p1", (CapabilityRef(name="db.read", scope="users"),))
    return gate


# ----------------------------- mocks --------------------------------------


class _FakeCasbin:
    """Минимальная заглушка с duck-type интерфейсом ``enforce``."""

    def __init__(self, allow: bool, raises: Exception | None = None) -> None:
        self._allow = allow
        self._raises = raises
        self.calls: list[tuple[str, str, str, str | None]] = []

    def enforce(
        self, user_id: str, resource: str, action: str, tenant_id: str | None = None
    ) -> bool:
        self.calls.append((user_id, resource, action, tenant_id))
        if self._raises is not None:
            raise self._raises
        return self._allow


@dataclass(slots=True)
class _FakePolicyDecision:
    allow: bool
    reasons: list[str]


class _FakeOPA:
    """Минимальная заглушка с async ``query`` методом."""

    def __init__(
        self,
        allow: bool,
        reasons: list[str] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._allow = allow
        self._reasons = reasons or []
        self._raises = raises
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def query(
        self, policy: str, input_doc: dict[str, Any]
    ) -> _FakePolicyDecision:
        self.calls.append((policy, dict(input_doc)))
        if self._raises is not None:
            raise self._raises
        return _FakePolicyDecision(allow=self._allow, reasons=list(self._reasons))


# ----------------------------- casbin_step --------------------------------


class TestCasbinStep:
    """S-L8-1: AuthorizationGateway.casbin_step factory."""

    async def test_casbin_allow_returns_allow_reason(self) -> None:
        casbin = _FakeCasbin(allow=True)
        step = AuthorizationGateway.casbin_step(casbin)
        reason = await step("p1", "orders", "read", {"tenant_id": "acme"})
        assert reason.source == "casbin"
        assert reason.outcome == "allow"
        assert reason.detail is None
        assert casbin.calls == [("p1", "orders", "read", "acme")]

    async def test_casbin_deny_returns_deny_reason(self) -> None:
        casbin = _FakeCasbin(allow=False)
        step = AuthorizationGateway.casbin_step(casbin)
        reason = await step("p1", "orders", "write", {"tenant_id": "acme"})
        assert reason.source == "casbin"
        assert reason.outcome == "deny"
        assert reason.detail == "casbin_enforce_denied"

    async def test_casbin_exception_is_fail_closed(self) -> None:
        casbin = _FakeCasbin(allow=True, raises=RuntimeError("boom"))
        step = AuthorizationGateway.casbin_step(casbin)
        reason = await step("p1", "orders", "read", {"tenant_id": "acme"})
        assert reason.outcome == "deny"
        assert reason.detail is not None
        assert "RuntimeError" in reason.detail


# ----------------------------- opa_step ------------------------------------


class TestOPAStep:
    """S-L8-2: AuthorizationGateway.opa_step factory."""

    async def test_opa_flag_off_returns_noop_allow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "opa_runtime_query_enabled", False)
        opa = _FakeOPA(allow=False)  # не должен быть вызван
        step = AuthorizationGateway.opa_step(opa, "authz/default")
        reason = await step("p1", "orders", "read", {})
        assert reason.outcome == "allow"
        assert reason.detail == "opa_runtime_query_enabled=False"
        assert opa.calls == []  # OPA не запрашивался

    async def test_opa_flag_on_allow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(feature_flags, "opa_runtime_query_enabled", True)
        opa = _FakeOPA(allow=True)
        step = AuthorizationGateway.opa_step(opa, "authz/default")
        reason = await step(
            "p1", "orders", "read", {"tenant_id": "acme", "correlation_id": "cid-1"}
        )
        assert reason.outcome == "allow"
        # input_doc должен содержать все 5 полей
        assert len(opa.calls) == 1
        policy_name, input_doc = opa.calls[0]
        assert policy_name == "authz/default"
        assert input_doc["principal"] == "p1"
        assert input_doc["resource"] == "orders"
        assert input_doc["action"] == "read"
        assert input_doc["tenant_id"] == "acme"
        assert input_doc["correlation_id"] == "cid-1"

    async def test_opa_flag_on_deny_with_reasons(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "opa_runtime_query_enabled", True)
        opa = _FakeOPA(allow=False, reasons=["role_missing", "tenant_mismatch"])
        step = AuthorizationGateway.opa_step(opa, "authz/default")
        reason = await step("p1", "orders", "write", {})
        assert reason.outcome == "deny"
        assert reason.detail == "role_missing,tenant_mismatch"

    async def test_opa_query_exception_is_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "opa_runtime_query_enabled", True)
        opa = _FakeOPA(allow=True, raises=ConnectionError("opa unreachable"))
        step = AuthorizationGateway.opa_step(opa, "authz/default")
        reason = await step("p1", "orders", "read", {})
        assert reason.outcome == "deny"
        assert reason.detail is not None
        assert "ConnectionError" in reason.detail


# ----------------------------- combined chain ------------------------------


class TestCombinedChain:
    """Композиция capability → casbin → opa в AuthorizationGateway."""

    async def test_full_chain_allow_all_three(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "opa_runtime_query_enabled", True)
        casbin = _FakeCasbin(allow=True)
        opa = _FakeOPA(allow=True)
        gateway = AuthorizationGateway(
            capability_gateway=_build_gate(),
            policies=(
                AuthorizationGateway.casbin_step(casbin),
                AuthorizationGateway.opa_step(opa, "authz/default"),
            ),
        )
        decision = await gateway.authorize(
            principal="p1",
            resource="db.read",
            action="check",
            context={"scope": "users", "tenant_id": "acme"},
        )
        assert decision.allowed is True
        sources = [r.source for r in decision.reasons]
        assert sources == ["capability_gateway", "casbin", "opa"]
        assert len(casbin.calls) == 1
        assert len(opa.calls) == 1

    async def test_casbin_deny_short_circuits_opa(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reason-chain order: capability allow → casbin deny → opa НЕ вызван."""
        monkeypatch.setattr(feature_flags, "opa_runtime_query_enabled", True)
        casbin = _FakeCasbin(allow=False)
        opa = _FakeOPA(allow=True)  # должен быть skipped
        gateway = AuthorizationGateway(
            capability_gateway=_build_gate(),
            policies=(
                AuthorizationGateway.casbin_step(casbin),
                AuthorizationGateway.opa_step(opa, "authz/default"),
            ),
        )
        decision = await gateway.authorize(
            principal="p1",
            resource="db.read",
            action="check",
            context={"scope": "users", "tenant_id": "acme"},
        )
        assert decision.allowed is False
        sources = [r.source for r in decision.reasons]
        # Capability allow, casbin deny, opa skipped
        assert sources == ["capability_gateway", "casbin"]
        assert decision.reasons[-1].outcome == "deny"
        assert opa.calls == []  # short-circuit verified
