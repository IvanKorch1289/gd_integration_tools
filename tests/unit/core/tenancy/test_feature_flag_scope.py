"""Sprint 7 Team T5 — unit-тесты TenantFeatureFlagResolver.

Покрывает:
    1. Без provider → fallback на локальный feature_flags.
    2. С provider + openfeature_external=False → fallback на local.
    3. С provider + openfeature_external=True → вызов provider.resolve_boolean.
    4. EvaluationContext собирается из current_tenant().
    5. Падение provider → fallback на local без исключения.
    6. get_string без provider → возвращает default.
    7. get_current_tenant_id возвращает None вне scope.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.tenancy import TenantContext, tenant_scope
from src.backend.core.tenancy.feature_flag_scope import TenantFeatureFlagResolver


class _LocalFeaturesStub:
    """Заглушка локального feature_flags singleton."""

    def __init__(self, **flags: bool) -> None:
        for name, val in flags.items():
            setattr(self, name, val)


class _FakeProvider:
    """Имитация OpenFeature provider для тестов."""

    def __init__(
        self,
        boolean_return: bool = True,
        string_return: str = "from_provider",
        raise_on_resolve: Exception | None = None,
    ) -> None:
        self.boolean_return = boolean_return
        self.string_return = string_return
        self.raise_on_resolve = raise_on_resolve
        self.last_eval_context: Any = None

    async def resolve_boolean_value(
        self,
        flag_key: str,
        default: bool,
        evaluation_context: Any | None = None,
    ) -> bool:
        self.last_eval_context = evaluation_context
        if self.raise_on_resolve:
            raise self.raise_on_resolve
        return self.boolean_return

    async def resolve_string_value(
        self,
        flag_key: str,
        default: str,
        evaluation_context: Any | None = None,
    ) -> str:
        self.last_eval_context = evaluation_context
        if self.raise_on_resolve:
            raise self.raise_on_resolve
        return self.string_return


@pytest.fixture
def disable_external_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """openfeature_external=False."""
    from src.backend.core.config import features as features_mod

    class _Stub:
        openfeature_external = False

    monkeypatch.setattr(features_mod, "feature_flags", _Stub())


@pytest.fixture
def enable_external_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """openfeature_external=True."""
    from src.backend.core.config import features as features_mod

    class _Stub:
        openfeature_external = True

    monkeypatch.setattr(features_mod, "feature_flags", _Stub())


@pytest.mark.asyncio
async def test_resolver_without_provider_uses_local(
    disable_external_flag: None,
) -> None:
    """Без provider резолвер читает локальный feature_flags."""
    local = _LocalFeaturesStub(my_flag=True)
    resolver = TenantFeatureFlagResolver(local_features=local)
    result = await resolver.is_enabled("my_flag", default=False)
    assert result is True


@pytest.mark.asyncio
async def test_resolver_returns_default_for_unknown_flag(
    disable_external_flag: None,
) -> None:
    """Для неизвестного flag возвращается default."""
    local = _LocalFeaturesStub()
    resolver = TenantFeatureFlagResolver(local_features=local)
    result = await resolver.is_enabled("missing_flag", default=True)
    assert result is True


@pytest.mark.asyncio
async def test_resolver_with_external_disabled_uses_local(
    disable_external_flag: None,
) -> None:
    """openfeature_external=False → provider не вызывается, читается local."""
    local = _LocalFeaturesStub(my_flag=True)
    provider = _FakeProvider(boolean_return=False)
    resolver = TenantFeatureFlagResolver(
        provider=provider, local_features=local
    )
    result = await resolver.is_enabled("my_flag", default=False)
    # Local говорит True, provider не должен вызваться.
    assert result is True
    assert provider.last_eval_context is None


@pytest.mark.asyncio
async def test_resolver_with_external_enabled_uses_provider(
    enable_external_flag: None,
) -> None:
    """openfeature_external=True → провайдер опрашивается."""
    local = _LocalFeaturesStub(my_flag=False)  # local говорит False
    provider = _FakeProvider(boolean_return=True)
    resolver = TenantFeatureFlagResolver(
        provider=provider, local_features=local
    )
    result = await resolver.is_enabled("my_flag", default=False)
    # Provider говорит True — это и должно вернуться.
    assert result is True
    assert provider.last_eval_context is not None


@pytest.mark.asyncio
async def test_resolver_builds_eval_context_from_tenant(
    enable_external_flag: None,
) -> None:
    """EvaluationContext.tenant_id берётся из current_tenant()."""
    provider = _FakeProvider(boolean_return=False)
    resolver = TenantFeatureFlagResolver(provider=provider)

    ctx = TenantContext(tenant_id="acme-corp", plan="enterprise", region="us")
    with tenant_scope(ctx):
        await resolver.is_enabled("foo", default=False)

    eval_ctx = provider.last_eval_context
    assert eval_ctx is not None
    assert eval_ctx.tenant_id == "acme-corp"
    assert eval_ctx.traits["plan"] == "enterprise"
    assert eval_ctx.traits["region"] == "us"


@pytest.mark.asyncio
async def test_resolver_falls_back_to_local_on_provider_failure(
    enable_external_flag: None,
) -> None:
    """Падение provider не пробрасывается — fallback на local."""
    local = _LocalFeaturesStub(my_flag=True)
    provider = _FakeProvider(raise_on_resolve=RuntimeError("network fail"))
    resolver = TenantFeatureFlagResolver(
        provider=provider, local_features=local
    )
    result = await resolver.is_enabled("my_flag", default=False)
    assert result is True


@pytest.mark.asyncio
async def test_get_string_without_provider_returns_default(
    disable_external_flag: None,
) -> None:
    """get_string без provider возвращает default (local не поддерживает string)."""
    resolver = TenantFeatureFlagResolver()
    result = await resolver.get_string("my_str", default="hello")
    assert result == "hello"


@pytest.mark.asyncio
async def test_get_string_with_provider_returns_provider_value(
    enable_external_flag: None,
) -> None:
    """get_string с включённым provider возвращает значение provider'а."""
    provider = _FakeProvider(string_return="from_external")
    resolver = TenantFeatureFlagResolver(provider=provider)
    result = await resolver.get_string("my_str", default="local")
    assert result == "from_external"


def test_get_current_tenant_id_none_outside_scope() -> None:
    """get_current_tenant_id возвращает None вне tenant_scope."""
    resolver = TenantFeatureFlagResolver()
    assert resolver.get_current_tenant_id() is None


def test_get_current_tenant_id_inside_scope() -> None:
    """get_current_tenant_id возвращает корректный tenant_id внутри scope."""
    resolver = TenantFeatureFlagResolver()
    ctx = TenantContext(tenant_id="my-tenant")
    with tenant_scope(ctx):
        assert resolver.get_current_tenant_id() == "my-tenant"
