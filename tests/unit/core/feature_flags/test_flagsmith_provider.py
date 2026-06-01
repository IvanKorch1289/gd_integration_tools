"""Sprint 7 Team T5 — unit-тесты FlagsmithProvider (OpenFeature adapter).

Покрывает:
    1. Default-OFF: provider возвращает default, когда openfeature_external=False.
    2. EvaluationContext dataclass корректно хранит tenant_id + traits.
    3. resolve_boolean_value возвращает default при отсутствии environment_key.
    4. resolve_string_value / resolve_integer_value / resolve_object_value — default fallback.
    5. is_external_provider_enabled() возвращает False при недоступном feature_flags.
    6. metadata содержит name + version.
    7. shutdown() безопасен при отсутствии client.
"""

from __future__ import annotations

import pytest

from src.backend.core.feature_flags.flagsmith_provider import (
    EvaluationContext,
    FlagsmithProvider,
    is_external_provider_enabled,
)


@pytest.fixture
def provider_no_env_key() -> FlagsmithProvider:
    """Provider без environment_key — всегда вернёт default."""
    return FlagsmithProvider(environment_key=None)


@pytest.fixture
def provider_with_env_key() -> FlagsmithProvider:
    """Provider с заглушенным environment_key."""
    return FlagsmithProvider(environment_key="ser.test-key")


@pytest.fixture
def disable_external_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Гарантирует openfeature_external=False для теста."""
    # Patch feature_flags singleton.
    from src.backend.core.config import features as features_mod

    class _FlagsStub:
        openfeature_external = False

    monkeypatch.setattr(features_mod, "feature_flags", _FlagsStub())


@pytest.fixture
def enable_external_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включает openfeature_external=True для теста."""
    from src.backend.core.config import features as features_mod

    class _FlagsStub:
        openfeature_external = True

    monkeypatch.setattr(features_mod, "feature_flags", _FlagsStub())


@pytest.mark.asyncio
async def test_resolve_boolean_returns_default_when_disabled(
    provider_with_env_key: FlagsmithProvider,
    disable_external_flag: None,
) -> None:
    """При openfeature_external=False resolve_boolean возвращает default."""
    result = await provider_with_env_key.resolve_boolean_value(
        "my_flag", default=True
    )
    assert result is True

    result_false = await provider_with_env_key.resolve_boolean_value(
        "my_flag", default=False
    )
    assert result_false is False


@pytest.mark.asyncio
async def test_resolve_string_returns_default_when_disabled(
    provider_with_env_key: FlagsmithProvider,
    disable_external_flag: None,
) -> None:
    """resolve_string возвращает default при disabled flag."""
    result = await provider_with_env_key.resolve_string_value(
        "my_str", default="fallback"
    )
    assert result == "fallback"


@pytest.mark.asyncio
async def test_resolve_integer_returns_default_when_disabled(
    provider_with_env_key: FlagsmithProvider,
    disable_external_flag: None,
) -> None:
    """resolve_integer возвращает default при disabled flag."""
    result = await provider_with_env_key.resolve_integer_value(
        "my_int", default=42
    )
    assert result == 42


@pytest.mark.asyncio
async def test_resolve_object_returns_default_when_disabled(
    provider_with_env_key: FlagsmithProvider,
    disable_external_flag: None,
) -> None:
    """resolve_object возвращает default при disabled flag."""
    default = {"hello": "world"}
    result = await provider_with_env_key.resolve_object_value(
        "my_obj", default=default
    )
    assert result == default


@pytest.mark.asyncio
async def test_resolve_returns_default_without_env_key(
    provider_no_env_key: FlagsmithProvider,
    enable_external_flag: None,
) -> None:
    """Без environment_key provider всегда возвращает default."""
    result = await provider_no_env_key.resolve_boolean_value(
        "x", default=False
    )
    assert result is False


def test_evaluation_context_defaults() -> None:
    """EvaluationContext без аргументов — tenant_id=None, traits={}."""
    ctx = EvaluationContext()
    assert ctx.tenant_id is None
    assert ctx.traits == {}


def test_evaluation_context_with_tenant() -> None:
    """EvaluationContext сохраняет tenant_id + traits."""
    ctx = EvaluationContext(tenant_id="acme", traits={"plan": "enterprise"})
    assert ctx.tenant_id == "acme"
    assert ctx.traits["plan"] == "enterprise"


def test_is_external_provider_enabled_default_off(
    disable_external_flag: None,
) -> None:
    """is_external_provider_enabled() возвращает False при disabled flag."""
    assert is_external_provider_enabled() is False


def test_is_external_provider_enabled_on(
    enable_external_flag: None,
) -> None:
    """is_external_provider_enabled() возвращает True при enabled flag."""
    assert is_external_provider_enabled() is True


def test_provider_metadata() -> None:
    """metadata содержит обязательные поля name + version."""
    provider = FlagsmithProvider()
    meta = provider.metadata
    assert meta["name"] == "FlagsmithProvider"
    assert "version" in meta


@pytest.mark.asyncio
async def test_shutdown_without_client_is_safe() -> None:
    """shutdown() без созданного client — no-op без исключений."""
    provider = FlagsmithProvider(environment_key="ser.key")
    # _client == None изначально.
    await provider.shutdown()  # не должно бросить
    assert provider._client is None


@pytest.mark.asyncio
async def test_shutdown_with_client_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """shutdown() вызывает aclose() на async-client."""
    provider = FlagsmithProvider(environment_key="ser.key")

    closed = {"called": False}

    class _FakeAsyncClient:
        async def aclose(self) -> None:
            closed["called"] = True

    provider._client = _FakeAsyncClient()
    await provider.shutdown()
    assert closed["called"] is True
    assert provider._client is None
