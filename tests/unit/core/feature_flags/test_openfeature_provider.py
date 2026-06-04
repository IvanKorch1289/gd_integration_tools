"""T-P0.1.13: unit-тесты для core/feature_flags/openfeature_provider.py (439 строк).

Coverage: openfeature_provider.py 32% → 75%+ через тестирование:
- EvaluationContext, OpenFeatureBackend Protocol
- InMemoryProvider (4 resolve_* методов, set_override, metadata)
- FlagsmithBackend (lazy init, fallback cascade, shutdown)
- Module-level helpers (is_flagsmith_backend_enabled, get_openfeature_backend, _coerce_ctx, _read_local_flag)
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.feature_flags.openfeature_provider import (
    EvaluationContext,
    FlagsmithBackend,
    InMemoryProvider,
    OpenFeatureBackend,
    _coerce_ctx,
    _read_local_flag,
    create_inmemory_backend,
    get_openfeature_backend,
    is_flagsmith_backend_enabled,
)


@pytest.fixture(autouse=True)
def _clean_env() -> Any:
    """Очищает ENV вокруг FEATURE_FLAG_BACKEND."""
    original = os.environ.pop("FEATURE_FLAG_BACKEND", None)
    yield
    if original is not None:
        os.environ["FEATURE_FLAG_BACKEND"] = original
    else:
        os.environ.pop("FEATURE_FLAG_BACKEND", None)


class TestEvaluationContext:
    def test_defaults(self) -> None:
        ctx = EvaluationContext()
        assert ctx.tenant_id is None
        assert ctx.traits == {}

    def test_with_data(self) -> None:
        ctx = EvaluationContext(tenant_id="t1", traits={"plan": "pro"})
        assert ctx.tenant_id == "t1"
        assert ctx.traits == {"plan": "pro"}

    def test_independent_dict_per_instance(self) -> None:
        c1 = EvaluationContext()
        c2 = EvaluationContext()
        c1.traits["x"] = 1
        assert "x" not in c2.traits


class TestProtocol:
    def test_isinstance(self) -> None:
        # InMemoryProvider соответствует Protocol structuraly
        assert isinstance(InMemoryProvider(), OpenFeatureBackend)


class TestInMemoryProvider:
    def test_init_no_overrides(self) -> None:
        p = InMemoryProvider()
        assert p._overrides == {}

    def test_init_with_overrides(self) -> None:
        p = InMemoryProvider(overrides={"k": "v"})
        assert p._overrides == {"k": "v"}

    def test_metadata(self) -> None:
        p = InMemoryProvider()
        m = p.metadata
        assert m["name"] == "InMemoryProvider"
        assert m["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_resolve_boolean_override(self) -> None:
        p = InMemoryProvider(overrides={"flag": True})
        result = await p.resolve_boolean_value("flag", default=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_resolve_boolean_runtime_override(self) -> None:
        """Runtime override > local flag > default."""
        p = InMemoryProvider()
        mock_runtime = MagicMock()
        mock_runtime.has_override.return_value = True
        mock_runtime.get.return_value = True
        with patch(
            "src.backend.core.feature_flags.runtime_overrides.get_runtime_overrides",
            return_value=mock_runtime,
        ):
            result = await p.resolve_boolean_value(
                "flag",
                default=False,
                evaluation_context=EvaluationContext(tenant_id="t1"),
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_resolve_boolean_local_flag(self) -> None:
        """Без overrides — читает локальный реестр."""
        p = InMemoryProvider()
        mock_flags = MagicMock()
        mock_flags.experimental_feature = True
        with patch("src.backend.core.config.features.feature_flags", mock_flags):
            result = await p.resolve_boolean_value(
                "experimental_feature", default=False
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_resolve_boolean_default(self) -> None:
        """Нет overrides, нет в local → default."""
        p = InMemoryProvider()
        mock_flags = MagicMock(spec=[])  # No attributes
        with patch("src.backend.core.config.features.feature_flags", mock_flags):
            result = await p.resolve_boolean_value("nonexistent", default=True)
            assert result is True

    @pytest.mark.asyncio
    async def test_resolve_string_override(self) -> None:
        p = InMemoryProvider(overrides={"flag": "value"})
        result = await p.resolve_string_value("flag", default="default")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_resolve_string_default(self) -> None:
        p = InMemoryProvider()
        result = await p.resolve_string_value("flag", default="default")
        assert result == "default"

    @pytest.mark.asyncio
    async def test_resolve_integer_override(self) -> None:
        p = InMemoryProvider(overrides={"flag": 42})
        result = await p.resolve_integer_value("flag", default=0)
        assert result == 42

    @pytest.mark.asyncio
    async def test_resolve_integer_default(self) -> None:
        p = InMemoryProvider()
        result = await p.resolve_integer_value("flag", default=99)
        assert result == 99

    @pytest.mark.asyncio
    async def test_resolve_object_override_dict(self) -> None:
        p = InMemoryProvider(overrides={"flag": {"k": "v"}})
        result = await p.resolve_object_value("flag", default={})
        assert result == {"k": "v"}

    @pytest.mark.asyncio
    async def test_resolve_object_override_non_dict(self) -> None:
        p = InMemoryProvider(overrides={"flag": "not-a-dict"})
        result = await p.resolve_object_value("flag", default={"x": 1})
        assert result == {"x": 1}

    @pytest.mark.asyncio
    async def test_resolve_object_default(self) -> None:
        p = InMemoryProvider()
        result = await p.resolve_object_value("flag", default={"x": 1})
        assert result == {"x": 1}

    def test_set_override(self) -> None:
        p = InMemoryProvider()
        p.set_override("k", "v")
        assert p._overrides == {"k": "v"}


class TestFlagsmithBackend:
    def test_init_defaults(self) -> None:
        b = FlagsmithBackend()
        assert b.environment_key is None
        assert b.api_url == "https://edge.api.flagsmith.com/api/v1/"
        assert b.request_timeout_seconds == 2.0
        # fallback default = InMemoryProvider
        assert isinstance(b.fallback, InMemoryProvider)
        assert b._provider is None

    def test_init_custom(self) -> None:
        custom_fb = InMemoryProvider(overrides={"x": 1})
        b = FlagsmithBackend(
            environment_key="env-key",
            api_url="https://custom.api/",
            request_timeout_seconds=5.0,
            fallback=custom_fb,
        )
        assert b.environment_key == "env-key"
        assert b.api_url == "https://custom.api/"
        assert b.request_timeout_seconds == 5.0
        assert b.fallback is custom_fb

    def test_metadata(self) -> None:
        b = FlagsmithBackend()
        m = b.metadata
        assert m["name"] == "FlagsmithBackend"
        assert m["version"] == "1.0.0"

    def test_get_provider_lazy(self) -> None:
        """Lazy init — _get_provider создаёт instance на первом вызове."""
        b = FlagsmithBackend(environment_key="key")
        assert b._provider is None
        with patch(
            "src.backend.core.feature_flags.flagsmith_provider.FlagsmithProvider"
        ) as MockProvider:
            provider = b._get_provider()
            assert MockProvider.called
            assert b._provider is provider
            # Второй вызов — тот же instance
            provider2 = b._get_provider()
            assert provider2 is provider

    @pytest.mark.asyncio
    async def test_resolve_boolean_success(self) -> None:
        b = FlagsmithBackend()
        mock_provider = MagicMock()
        mock_provider.resolve_boolean_value = AsyncMock(return_value=True)
        b._provider = mock_provider

        result = await b.resolve_boolean_value("flag", default=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_resolve_boolean_default_match_triggers_fallback(self) -> None:
        """Если Flagsmith вернул default — fallback."""
        b = FlagsmithBackend(fallback=InMemoryProvider(overrides={"flag": True}))
        mock_provider = MagicMock()
        mock_provider.resolve_boolean_value = AsyncMock(return_value=False)
        b._provider = mock_provider

        result = await b.resolve_boolean_value("flag", default=False)
        assert result is True  # fallback override

    @pytest.mark.asyncio
    async def test_resolve_boolean_provider_raises_fallback(self) -> None:
        b = FlagsmithBackend(fallback=InMemoryProvider(overrides={"flag": True}))
        mock_provider = MagicMock()
        mock_provider.resolve_boolean_value = AsyncMock(
            side_effect=ConnectionError("flagsmith-down")
        )
        b._provider = mock_provider

        with patch(
            "src.backend.core.feature_flags.openfeature_provider._logger"
        ) as mock_logger:
            result = await b.resolve_boolean_value("flag", default=False)
            assert result is True  # fallback
            assert mock_logger.warning.called

    @pytest.mark.asyncio
    async def test_resolve_string_success(self) -> None:
        b = FlagsmithBackend()
        mock_provider = MagicMock()
        mock_provider.resolve_string_value = AsyncMock(return_value="hello")
        b._provider = mock_provider

        result = await b.resolve_string_value("flag", default="default")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_resolve_string_default_match_triggers_fallback(self) -> None:
        b = FlagsmithBackend(fallback=InMemoryProvider(overrides={"flag": "fb"}))
        mock_provider = MagicMock()
        mock_provider.resolve_string_value = AsyncMock(return_value="default")
        b._provider = mock_provider

        result = await b.resolve_string_value("flag", default="default")
        assert result == "fb"

    @pytest.mark.asyncio
    async def test_resolve_string_provider_raises(self) -> None:
        b = FlagsmithBackend(fallback=InMemoryProvider(overrides={"flag": "fb"}))
        mock_provider = MagicMock()
        mock_provider.resolve_string_value = AsyncMock(side_effect=RuntimeError("err"))
        b._provider = mock_provider

        result = await b.resolve_string_value("flag", default="default")
        assert result == "fb"

    @pytest.mark.asyncio
    async def test_resolve_integer_success(self) -> None:
        b = FlagsmithBackend()
        mock_provider = MagicMock()
        mock_provider.resolve_integer_value = AsyncMock(return_value=42)
        b._provider = mock_provider

        result = await b.resolve_integer_value("flag", default=0)
        assert result == 42

    @pytest.mark.asyncio
    async def test_resolve_integer_provider_raises(self) -> None:
        b = FlagsmithBackend(fallback=InMemoryProvider(overrides={"flag": 100}))
        mock_provider = MagicMock()
        mock_provider.resolve_integer_value = AsyncMock(side_effect=Exception("err"))
        b._provider = mock_provider

        result = await b.resolve_integer_value("flag", default=0)
        assert result == 100

    @pytest.mark.asyncio
    async def test_resolve_object_success(self) -> None:
        b = FlagsmithBackend()
        mock_provider = MagicMock()
        mock_provider.resolve_object_value = AsyncMock(return_value={"k": "v"})
        b._provider = mock_provider

        result = await b.resolve_object_value("flag", default={})
        assert result == {"k": "v"}

    @pytest.mark.asyncio
    async def test_resolve_object_provider_raises(self) -> None:
        b = FlagsmithBackend(fallback=InMemoryProvider(overrides={"flag": {"x": 1}}))
        mock_provider = MagicMock()
        mock_provider.resolve_object_value = AsyncMock(side_effect=Exception("err"))
        b._provider = mock_provider

        result = await b.resolve_object_value("flag", default={})
        assert result == {"x": 1}

    @pytest.mark.asyncio
    async def test_shutdown_no_provider(self) -> None:
        b = FlagsmithBackend()
        await b.shutdown()  # No error

    @pytest.mark.asyncio
    async def test_shutdown_with_provider(self) -> None:
        b = FlagsmithBackend()
        mock_provider = MagicMock()
        mock_provider.shutdown = AsyncMock()
        b._provider = mock_provider

        await b.shutdown()
        mock_provider.shutdown.assert_called_once()
        assert b._provider is None

    @pytest.mark.asyncio
    async def test_shutdown_provider_raises(self) -> None:
        b = FlagsmithBackend()
        mock_provider = MagicMock()
        mock_provider.shutdown = AsyncMock(side_effect=RuntimeError("err"))
        b._provider = mock_provider

        with patch(
            "src.backend.core.feature_flags.openfeature_provider._logger"
        ) as mock_logger:
            await b.shutdown()
            assert mock_logger.exception.called
            assert b._provider is None

    @pytest.mark.asyncio
    async def test_shutdown_provider_no_shutdown_method(self) -> None:
        b = FlagsmithBackend()
        mock_provider = MagicMock(spec=[])  # No shutdown
        b._provider = mock_provider

        await b.shutdown()
        assert b._provider is None


class TestCoerceCtx:
    def test_none_returns_none(self) -> None:
        result = _coerce_ctx(None, EvaluationContext)
        assert result is None

    def test_copies_fields(self) -> None:
        ctx = EvaluationContext(tenant_id="t1", traits={"a": 1})
        result = _coerce_ctx(ctx, EvaluationContext)
        assert result.tenant_id == "t1"
        assert result.traits == {"a": 1}
        # Копия — изменения не затронут original
        result.traits["b"] = 2
        assert "b" not in ctx.traits


class TestReadLocalFlag:
    def test_reads_attribute(self) -> None:
        mock_flags = MagicMock()
        mock_flags.some_flag = True
        with patch("src.backend.core.config.features.feature_flags", mock_flags):
            assert _read_local_flag("some_flag", default=False) is True

    def test_returns_default_if_missing(self) -> None:
        mock_flags = MagicMock(spec=[])
        with patch("src.backend.core.config.features.feature_flags", mock_flags):
            assert _read_local_flag("missing", default=True) is True

    def test_returns_default_on_exception(self) -> None:
        """Если import feature_flags raises — default."""
        import sys

        # Удаляем cached module → import will fail
        with patch.dict(sys.modules, {"src.backend.core.config.features": None}):
            assert _read_local_flag("any", default=False) is False


class TestIsFlagsmithBackendEnabled:
    def test_env_not_set(self) -> None:
        assert is_flagsmith_backend_enabled() is False

    def test_env_set_to_other(self) -> None:
        os.environ["FEATURE_FLAG_BACKEND"] = "other"
        assert is_flagsmith_backend_enabled() is False

    def test_env_set_case_insensitive(self) -> None:
        os.environ["FEATURE_FLAG_BACKEND"] = "FLAGSMITH"
        # Env lowercase check → "flagsmith" matches
        mock_flags = MagicMock()
        mock_flags.openfeature_flagsmith_backend = True
        with patch("src.backend.core.config.features.feature_flags", mock_flags):
            assert is_flagsmith_backend_enabled() is True

    def test_env_set_flag_off(self) -> None:
        os.environ["FEATURE_FLAG_BACKEND"] = "flagsmith"
        mock_flags = MagicMock(spec=[])  # Flag attribute missing
        with patch("src.backend.core.config.features.feature_flags", mock_flags):
            assert is_flagsmith_backend_enabled() is False


class TestCreateInmemoryBackend:
    def test_no_overrides(self) -> None:
        b = create_inmemory_backend()
        assert isinstance(b, InMemoryProvider)
        assert b._overrides == {}

    def test_with_overrides(self) -> None:
        b = create_inmemory_backend(overrides={"k": "v"})
        assert b._overrides == {"k": "v"}


class TestGetOpenfeatureBackend:
    def test_default_inmemory(self) -> None:
        b = get_openfeature_backend()
        assert isinstance(b, InMemoryProvider)

    def test_inmemory_with_overrides(self) -> None:
        b = get_openfeature_backend(inmemory_overrides={"k": "v"})
        assert isinstance(b, InMemoryProvider)
        assert b._overrides == {"k": "v"}

    def test_flagsmith_when_enabled(self) -> None:
        os.environ["FEATURE_FLAG_BACKEND"] = "flagsmith"
        mock_flags = MagicMock()
        mock_flags.openfeature_flagsmith_backend = True
        with patch("src.backend.core.config.features.feature_flags", mock_flags):
            b = get_openfeature_backend()
            assert isinstance(b, FlagsmithBackend)
            assert b.environment_key is None  # No FLAGSMITH_ENVIRONMENT_KEY

    def test_flagsmith_with_env_key(self) -> None:
        os.environ["FEATURE_FLAG_BACKEND"] = "flagsmith"
        os.environ["FLAGSMITH_ENVIRONMENT_KEY"] = "env-key"
        mock_flags = MagicMock()
        mock_flags.openfeature_flagsmith_backend = True
        with patch("src.backend.core.config.features.feature_flags", mock_flags):
            b = get_openfeature_backend()
            assert isinstance(b, FlagsmithBackend)
            assert b.environment_key == "env-key"


class TestAllExports:
    def test_all(self) -> None:
        from src.backend.core.feature_flags import openfeature_provider as m

        assert set(m.__all__) == {
            "EvaluationContext",
            "FlagsmithBackend",
            "InMemoryProvider",
            "OpenFeatureBackend",
            "create_inmemory_backend",
            "get_openfeature_backend",
            "is_flagsmith_backend_enabled",
        }
