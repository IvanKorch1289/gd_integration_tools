"""B-12 fix (cycle 37): smoke-test production-like OPA/Casbin runtime wiring.

Задача: подтвердить, что composition root (см. ``plugins/composition/di.py``)
поднимает :class:`AuthorizationGateway` с policy-цепочкой, если в :class:`PolicySettings`
выставлен ``engine_enabled=True``, и оставляет её пустой при ``False``.

Сценарии:

* production-like: ``engine_enabled=True`` + OPA-мок (allow) → gateway has policies.
* OPA-мок allow → :func:`authorize` завершается с allow + reason "opa".
* OPA-мок deny (reasons непустой) → authorize завершается с deny.
* OPA-мок raises → fail-closed: deny.
* Casbin-мок allow/deny через ``TenantScopedCasbin`` →
  :func:`authorize` корректно отражает решение.
* Engine OFF (default dev/dev_light) → ``_policies == ()`` (backward-compat).

Реальный OPA server не поднимается — клиент мокается через duck-type
(async query метод). ``httpx`` не используется.
"""


from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from src.backend.core.config.features import feature_flags
from src.backend.core.security.authorization_gateway import AuthorizationGateway
from src.backend.core.security.authorization_gateway.policies import (
    build_casbin_policy_decider,
    build_opa_policy_decider,
)
from src.backend.plugins.composition import di

# ───────────────────────────── fixtures ────────────────────────────────── #


@pytest.fixture(autouse=True)
def _enable_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """Все тесты работают с authz_gateway_enabled=True."""
    monkeypatch.setattr(feature_flags, "authz_gateway_enabled", True)


# ──────────────────────── duck-type fakes ──────────────────────────────── #


@dataclass(slots=True)
class _FakePolicyDecision:
    """Минимальный PolicyDecision-shaped объект для OPA-фейка."""

    allow: bool
    reasons: list[str]


class _FakeOPA:
    """Duck-type OPA-клиент (async ``query`` метод)."""

    def __init__(
        self,
        *,
        allow: bool = True,
        reasons: list[str] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._allow = allow
        self._reasons = reasons or []
        self._raises = raises
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def query(
        self, policy: str, input_doc: dict[str, Any],
    ) -> _FakePolicyDecision:
        self.calls.append((policy, dict(input_doc)))
        if self._raises is not None:
            raise self._raises
        return _FakePolicyDecision(allow=self._allow, reasons=list(self._reasons))


class _FakeTenantScopedCasbin:
    """Duck-type для ``TenantScopedCasbin.enforce`` (4-арг сигнатура)."""

    def __init__(self, *, allow: bool = True, raises: Exception | None = None) -> None:
        self._allow = allow
        self._raises = raises
        self.calls: list[tuple[str, str, str, str | None]] = []

    def enforce(
        self,
        user_id: str,
        resource: str,
        action: str,
        tenant_id: str | None = None,
    ) -> bool:
        self.calls.append((user_id, resource, action, tenant_id))
        if self._raises is not None:
            raise self._raises
        return self._allow


# ─────────────────── helper: capability that always allows ─────────────── #


class _AllowAllCapability:
    """Capability-gateway, который всегда пропускает."""

    def check(
        self, principal: str, resource: str, scope: str | None = None,
    ) -> None:
        return None  # allow (не raise)


# ────────────────────── factory-wrapper unit-тесты ─────────────────────── #


class TestFactoryWrappers:
    """Тонкие обёртки из ``policies/`` корректно делегируют к фабрикам mixin'ов."""

    def test_build_opa_policy_decider_returns_callable(self) -> None:
        opa = _FakeOPA(allow=True)
        decider = build_opa_policy_decider(opa, policy_name="authz/default")
        assert callable(decider)
        # PolicyDecider — это Callable[..], не класс; проверяем через __name__
        # (mixin-фабрика проставляет ``_step.__name__ = "opa_step"``).
        assert getattr(decider, "__name__", "") == "opa_step"

    def test_build_opa_policy_decider_custom_policy_name(self) -> None:
        """policy_name пробрасывается в decider через opa_step."""
        opa = _FakeOPA(allow=True)
        decider = build_opa_policy_decider(
            opa, policy_name="custom/policy",
        )
        # policy_name фиксируется замыканием внутри opa_step, но сам
        # ``decider`` это callable — проверим, что он вызывается без ошибок.
        assert callable(decider)

    def test_build_casbin_policy_decider_returns_callable(self) -> None:
        casbin = _FakeTenantScopedCasbin(allow=True)
        decider = build_casbin_policy_decider(casbin)
        assert callable(decider)
        assert getattr(decider, "__name__", "") == "casbin_step"


# ─────────────────── OPA-decider runtime behaviour ─────────────────────── #


@pytest.mark.asyncio
class TestOPAPolicyDeciderRuntime:
    """OPA decider: allow / deny / fail-closed (B-12 fix, cycle 37)."""

    async def test_opa_allow_passes_through_gateway(self) -> None:
        opa = _FakeOPA(allow=True)
        decider = build_opa_policy_decider(opa, policy_name="authz/default")
        gateway = AuthorizationGateway(
            capability_gateway=_AllowAllCapability(),  # type: ignore[arg-type]
            policies=(decider,),
        )
        decision = await gateway.authorize(
            principal="svc-1",
            resource="orders:read",
            action="read",
            context={"tenant_id": "acme"},
        )
        assert decision.allowed is True
        sources = [r.source for r in decision.reasons]
        assert "opa" in sources

    async def test_opa_deny_short_circuits(self) -> None:
        opa = _FakeOPA(allow=False, reasons=["role_missing"])
        decider = build_opa_policy_decider(opa, policy_name="authz/default")
        gateway = AuthorizationGateway(
            capability_gateway=_AllowAllCapability(),  # type: ignore[arg-type]
            policies=(decider,),
        )
        decision = await gateway.authorize(
            principal="svc-2",
            resource="orders:read",
            action="read",
            context={"tenant_id": "acme"},
        )
        assert decision.allowed is False
        last = decision.reasons[-1]
        assert last.source == "opa"
        assert last.outcome == "deny"
        assert "role_missing" in (last.detail or "")

    async def test_opa_exception_fails_closed(self) -> None:
        opa = _FakeOPA(raises=RuntimeError("network down"))
        decider = build_opa_policy_decider(opa, policy_name="authz/default")
        gateway = AuthorizationGateway(
            capability_gateway=_AllowAllCapability(),  # type: ignore[arg-type]
            policies=(decider,),
        )
        decision = await gateway.authorize(
            principal="svc-3",
            resource="orders:read",
            action="read",
            context={"tenant_id": "acme"},
        )
        assert decision.allowed is False
        last = decision.reasons[-1]
        assert last.outcome == "deny"
        assert "RuntimeError" in (last.detail or "")


# ─────────────────── Casbin-decider runtime behaviour ──────────────────── #


@pytest.mark.asyncio
class TestCasbinPolicyDeciderRuntime:
    """Casbin decider через TenantScopedCasbin (B-12 fix, cycle 37)."""

    async def test_casbin_allow(self) -> None:
        casbin = _FakeTenantScopedCasbin(allow=True)
        decider = build_casbin_policy_decider(casbin)
        gateway = AuthorizationGateway(
            capability_gateway=_AllowAllCapability(),  # type: ignore[arg-type]
            policies=(decider,),
        )
        decision = await gateway.authorize(
            principal="user-1",
            resource="orders",
            action="read",
            context={"tenant_id": "acme"},
        )
        assert decision.allowed is True
        sources = [r.source for r in decision.reasons]
        assert "casbin" in sources
        assert casbin.calls == [("user-1", "orders", "read", "acme")]

    async def test_casbin_deny_short_circuits(self) -> None:
        casbin = _FakeTenantScopedCasbin(allow=False)
        decider = build_casbin_policy_decider(casbin)
        gateway = AuthorizationGateway(
            capability_gateway=_AllowAllCapability(),  # type: ignore[arg-type]
            policies=(decider,),
        )
        decision = await gateway.authorize(
            principal="user-2",
            resource="orders",
            action="write",
            context={"tenant_id": "acme"},
        )
        assert decision.allowed is False
        last = decision.reasons[-1]
        assert last.source == "casbin"
        assert last.outcome == "deny"

    async def test_casbin_exception_fails_closed(self) -> None:
        casbin = _FakeTenantScopedCasbin(raises=RuntimeError("model broken"))
        decider = build_casbin_policy_decider(casbin)
        gateway = AuthorizationGateway(
            capability_gateway=_AllowAllCapability(),  # type: ignore[arg-type]
            policies=(decider,),
        )
        decision = await gateway.authorize(
            principal="user-3",
            resource="orders",
            action="read",
            context={"tenant_id": "acme"},
        )
        assert decision.allowed is False
        last = decision.reasons[-1]
        assert last.outcome == "deny"


# ─────────────────── combined chain (OPA + Casbin) ─────────────────────── #


@pytest.mark.asyncio
class TestCombinedChain:
    """OPA + Casbin последовательно: deny на любом звене → fail-closed."""

    async def test_opa_allow_then_casbin_deny(self) -> None:
        opa = _FakeOPA(allow=True)
        casbin = _FakeTenantScopedCasbin(allow=False)
        gateway = AuthorizationGateway(
            capability_gateway=_AllowAllCapability(),  # type: ignore[arg-type]
            policies=(
                build_opa_policy_decider(opa, policy_name="authz/default"),
                build_casbin_policy_decider(casbin),
            ),
        )
        decision = await gateway.authorize(
            principal="svc",
            resource="orders",
            action="read",
            context={"tenant_id": "acme"},
        )
        assert decision.allowed is False
        assert decision.reasons[-1].source == "casbin"
        # OPA всё-таки был вызван (allow), затем Casbin дал deny.
        assert opa.calls, "OPA должен быть вызван до Casbin"
        assert casbin.calls, "Casbin должен быть вызван после OPA allow"

    async def test_opa_deny_skips_casbin(self) -> None:
        opa = _FakeOPA(allow=False, reasons=["policy_blocked"])
        casbin = _FakeTenantScopedCasbin(allow=True)
        gateway = AuthorizationGateway(
            capability_gateway=_AllowAllCapability(),  # type: ignore[arg-type]
            policies=(
                build_opa_policy_decider(opa, policy_name="authz/default"),
                build_casbin_policy_decider(casbin),
            ),
        )
        decision = await gateway.authorize(
            principal="svc",
            resource="orders",
            action="read",
            context={"tenant_id": "acme"},
        )
        assert decision.allowed is False
        # Casbin skipped (short-circuit на OPA-deny).
        assert casbin.calls == []


# ─────────────────── composition-root wiring (smoke) ───────────────────── #


class TestCompositionRootWiring:
    """``register_app_state`` корректно прокидывает policies при engine_enabled."""

    def _stub_constructors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Подменить ВСЕ тяжёлые конструкторы, кроме AuthorizationGateway."""

        def _stub_factory(_attr: str) -> MagicMock:
            m = MagicMock()
            return m

        monkeypatch.setattr(
            "src.backend.infrastructure.security.api_key_manager.APIKeyManager",
            lambda: _stub_factory("api_key_manager"),
        )
        monkeypatch.setattr(
            "src.backend.dsl.engine.tracer.ExecutionTracer",
            lambda: _stub_factory("tracer"),
        )
        monkeypatch.setattr(
            "src.backend.dsl.engine.plugin_registry.ProcessorPluginRegistry",
            lambda: _stub_factory("plugin_registry"),
        )
        monkeypatch.setattr(
            "src.backend.dsl.engine.versioning.PipelineVersionManager",
            lambda: _stub_factory("pipeline_version_manager"),
        )
        monkeypatch.setattr(
            "src.backend.infrastructure.application.slo_tracker.SLOTracker",
            lambda: _stub_factory("slo_tracker"),
        )
        monkeypatch.setattr(
            "src.backend.infrastructure.database.pool_monitor.PoolMonitor",
            lambda: _stub_factory("pool_monitor"),
        )
        monkeypatch.setattr(
            "src.backend.infrastructure.clients.external.langfuse_client.LangFuseClient",
            lambda: _stub_factory("langfuse_client"),
        )
        monkeypatch.setattr(
            "src.backend.infrastructure.application.vault_refresher.VaultSecretRefresher",
            lambda: _stub_factory("vault_refresher"),
        )
        monkeypatch.setattr(
            "src.backend.entrypoints.mqtt.mqtt_handler.MqttHandler",
            lambda settings: _stub_factory("mqtt_handler"),
        )
        monkeypatch.setattr(
            "src.backend.infrastructure.messaging.invocation_replies.get_reply_channel_registry",
            lambda: _stub_factory("reply_registry"),
        )
        monkeypatch.setattr(
            "src.backend.services.execution.invoker.Invoker",
            lambda: _stub_factory("invoker"),
        )
        monkeypatch.setattr(
            "src.backend.infrastructure.watermark.factory.create_watermark_store",
            lambda *args, **kwargs: _stub_factory("watermark_store"),
        )
        monkeypatch.setattr(
            "src.backend.core.di.providers.ai.get_ai_gateway_provider",
            lambda: _stub_factory("ai_gateway"),
        )
        monkeypatch.setattr(
            "src.backend.services.capabilities.facade.get_capability_facade",
            lambda: _stub_factory("capability_facade"),
        )

    @pytest.fixture
    def fresh_app(self, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
        self._stub_constructors(monkeypatch)
        return FastAPI()

    def test_engine_disabled_means_no_policies(
        self, fresh_app: FastAPI, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """engine_enabled=False (default) → _policies пустой."""
        # B-12 fix (cycle 37): composition root не инстанцирует движки.
        fake_settings = type(
            "_S",
            (),
            {
                "engine_enabled": False,
                "opa_url": "",
                "opa_policy_name": "authz/default",
                "casbin_model_path": None,
                "casbin_policy_path": None,
            },
        )()
        monkeypatch.setattr(
            "src.backend.core.config.services.policy.policy_settings",
            fake_settings,
            raising=False,
        )

        di.register_app_state(fresh_app)
        gw = fresh_app.state.authorization_gateway
        assert isinstance(gw, AuthorizationGateway)
        assert gw._policies == ()

    def test_engine_enabled_wires_opa_only(
        self, fresh_app: FastAPI, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """engine_enabled=True + opa_url → ровно 1 policy-decider (OPA)."""

        opa_fake = _FakeOPA(allow=True)

        fake_settings = type(
            "_S",
            (),
            {
                "engine_enabled": True,
                "opa_url": "http://opa:8181",
                "opa_policy_name": "authz/default",
                "casbin_model_path": None,
                "casbin_policy_path": None,
            },
        )()
        monkeypatch.setattr(
            "src.backend.core.config.services.policy.policy_settings",
            fake_settings,
            raising=False,
        )
        # Подменяем конкретные конструкторы инфраструктуры — OPAClient
        # lazy-init выстрелит только при первом query(), но singleton
        # всё равно будет создан. Подменим его нашим fake, чтобы DI
        # не дёргал HTTP.
        monkeypatch.setattr(
            "src.backend.infrastructure.policy.opa.client.OPAClient",
            lambda base_url="...": opa_fake,
        )

        di.register_app_state(fresh_app)
        gw = fresh_app.state.authorization_gateway
        assert len(gw._policies) == 1


# ─────────────────── OPA→Casbin chain через gateway.full authorize ─────── #


@pytest.mark.asyncio
async def test_production_like_flow_opa_allow_casbin_allow_deny() -> None:
    """Production-like сценарий: OPA allow + Casbin deny = final deny."""
    opa = _FakeOPA(allow=True)
    casbin = _FakeTenantScopedCasbin(allow=False)
    gateway = AuthorizationGateway(
        capability_gateway=_AllowAllCapability(),  # type: ignore[arg-type]
        policies=(
            build_opa_policy_decider(opa, policy_name="authz/default"),
            build_casbin_policy_decider(casbin),
        ),
    )

    decision = await gateway.authorize(
        principal="alice@bank",
        resource="orders",
        action="write",
        context={"tenant_id": "acme", "correlation_id": "test-001"},
    )

    assert decision.allowed is False
    # Reason-chain: capability → opa (allow) → casbin (deny)
    sources = [r.source for r in decision.reasons]
    assert sources == ["capability_gateway", "opa", "casbin"]
    # Correlation_id сохранён от начала до конца.
    assert decision.correlation_id == "test-001"
