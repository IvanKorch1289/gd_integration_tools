"""T-P0.1.15: unit-тесты для core/feature_flags/flagsmith_provider.py (FlagsmithProvider).

Coverage: flagsmith_provider.py 53% → 95%+ через тестирование:
- EvaluationContext, ProviderError
- is_external_provider_enabled
- FlagsmithProvider (4× resolve_*, shutdown, _get_client)
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.feature_flags.flagsmith_provider import (
    EvaluationContext,
    FlagsmithProvider,
    ProviderError,
    is_external_provider_enabled,
)


class TestEvaluationContext:
    def test_defaults(self) -> None:
        ctx = EvaluationContext()
        assert ctx.tenant_id is None
        assert ctx.traits == {}

    def test_with_data(self) -> None:
        ctx = EvaluationContext(tenant_id="t1", traits={"plan": "pro"})
        assert ctx.tenant_id == "t1"
        assert ctx.traits == {"plan": "pro"}

    def test_independent_dict(self) -> None:
        c1 = EvaluationContext()
        c2 = EvaluationContext()
        c1.traits["x"] = 1
        assert "x" not in c2.traits


class TestProviderError:
    def test_inherits_runtime_error(self) -> None:
        err = ProviderError("test")
        assert isinstance(err, RuntimeError)
        assert "test" in str(err)


class TestIsExternalProviderEnabled:
    def test_flag_off(self) -> None:
        mock_flags = MagicMock(spec=[])
        with patch("src.backend.core.config.features.feature_flags", mock_flags):
            assert is_external_provider_enabled() is False

    def test_flag_on(self) -> None:
        mock_flags = MagicMock()
        mock_flags.openfeature_external = True
        with patch("src.backend.core.config.features.feature_flags", mock_flags):
            assert is_external_provider_enabled() is True

    def test_flag_off_explicitly(self) -> None:
        mock_flags = MagicMock()
        mock_flags.openfeature_external = False
        with patch("src.backend.core.config.features.feature_flags", mock_flags):
            assert is_external_provider_enabled() is False

    def test_exception_returns_false(self) -> None:
        """Если feature_flags module unavailable — False (default-OFF)."""
        with patch.dict(sys.modules, {"src.backend.core.config.features": None}):
            assert is_external_provider_enabled() is False


class TestInit:
    def test_defaults(self) -> None:
        p = FlagsmithProvider(environment_key="key")
        assert p.environment_key == "key"
        assert p.api_url == "https://edge.api.flagsmith.com/api/v1/"
        assert p.request_timeout_seconds == 2.0
        assert p._client is None

    def test_no_key(self) -> None:
        p = FlagsmithProvider()
        assert p.environment_key is None

    def test_custom_params(self) -> None:
        p = FlagsmithProvider(
            environment_key="k",
            api_url="https://custom.api/",
            request_timeout_seconds=5.0,
        )
        assert p.api_url == "https://custom.api/"
        assert p.request_timeout_seconds == 5.0


class TestMetadata:
    def test_metadata(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        m = p.metadata
        assert m["name"] == "FlagsmithProvider"
        assert m["version"] == "1.0.0"


class TestResolveBoolean:
    @pytest.mark.asyncio
    async def test_disabled_returns_default(self) -> None:
        """Flag off — default."""
        p = FlagsmithProvider(environment_key="k")
        with patch.object(p, "_enabled", return_value=False):
            result = await p.resolve_boolean_value("flag", default=True)
            assert result is True

    @pytest.mark.asyncio
    async def test_no_key_returns_default(self) -> None:
        """No environment_key — _get_client returns None → default."""
        p = FlagsmithProvider()  # no key
        with patch.object(p, "_enabled", return_value=True):
            result = await p.resolve_boolean_value("flag", default=False)
            assert result is False

    @pytest.mark.asyncio
    async def test_provider_error_returns_default(self) -> None:
        """ProviderError на _get_client → default."""
        p = FlagsmithProvider(environment_key="k")
        with patch.object(p, "_enabled", return_value=True):
            with patch.object(p, "_get_client", side_effect=ProviderError("err")):
                with patch(
                    "src.backend.core.feature_flags.flagsmith_provider._logger"
                ) as mock_logger:
                    result = await p.resolve_boolean_value("flag", default=True)
                    assert result is True
                    assert mock_logger.warning.called

    @pytest.mark.asyncio
    async def test_with_client_returns_default(self) -> None:
        """В текущей реализации всегда default (production-rollout note)."""
        p = FlagsmithProvider(environment_key="k")
        with patch.object(p, "_enabled", return_value=True):
            with patch.object(p, "_get_client", return_value=MagicMock()):
                result = await p.resolve_boolean_value("flag", default=True)
                assert result is True


class TestResolveString:
    @pytest.mark.asyncio
    async def test_disabled(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        with patch.object(p, "_enabled", return_value=False):
            result = await p.resolve_string_value("flag", default="d")
            assert result == "d"

    @pytest.mark.asyncio
    async def test_no_key(self) -> None:
        p = FlagsmithProvider()
        with patch.object(p, "_enabled", return_value=True):
            result = await p.resolve_string_value("flag", default="d")
            assert result == "d"

    @pytest.mark.asyncio
    async def test_provider_error(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        with patch.object(p, "_enabled", return_value=True):
            with patch.object(p, "_get_client", side_effect=ProviderError("err")):
                result = await p.resolve_string_value("flag", default="d")
                assert result == "d"

    @pytest.mark.asyncio
    async def test_with_client(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        with patch.object(p, "_enabled", return_value=True):
            with patch.object(p, "_get_client", return_value=MagicMock()):
                result = await p.resolve_string_value("flag", default="d")
                assert result == "d"


class TestResolveInteger:
    @pytest.mark.asyncio
    async def test_disabled(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        with patch.object(p, "_enabled", return_value=False):
            result = await p.resolve_integer_value("flag", default=42)
            assert result == 42

    @pytest.mark.asyncio
    async def test_no_key(self) -> None:
        p = FlagsmithProvider()
        with patch.object(p, "_enabled", return_value=True):
            result = await p.resolve_integer_value("flag", default=42)
            assert result == 42

    @pytest.mark.asyncio
    async def test_provider_error(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        with patch.object(p, "_enabled", return_value=True):
            with patch.object(p, "_get_client", side_effect=ProviderError("err")):
                result = await p.resolve_integer_value("flag", default=42)
                assert result == 42

    @pytest.mark.asyncio
    async def test_with_client(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        with patch.object(p, "_enabled", return_value=True):
            with patch.object(p, "_get_client", return_value=MagicMock()):
                result = await p.resolve_integer_value("flag", default=42)
                assert result == 42


class TestResolveObject:
    @pytest.mark.asyncio
    async def test_disabled(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        with patch.object(p, "_enabled", return_value=False):
            result = await p.resolve_object_value("flag", default={"x": 1})
            assert result == {"x": 1}

    @pytest.mark.asyncio
    async def test_no_key(self) -> None:
        p = FlagsmithProvider()
        with patch.object(p, "_enabled", return_value=True):
            result = await p.resolve_object_value("flag", default={"x": 1})
            assert result == {"x": 1}

    @pytest.mark.asyncio
    async def test_provider_error(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        with patch.object(p, "_enabled", return_value=True):
            with patch.object(p, "_get_client", side_effect=ProviderError("err")):
                result = await p.resolve_object_value("flag", default={"x": 1})
                assert result == {"x": 1}

    @pytest.mark.asyncio
    async def test_with_client(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        with patch.object(p, "_enabled", return_value=True):
            with patch.object(p, "_get_client", return_value=MagicMock()):
                result = await p.resolve_object_value("flag", default={"x": 1})
                assert result == {"x": 1}


class TestShutdown:
    @pytest.mark.asyncio
    async def test_no_client(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        await p.shutdown()
        assert p._client is None

    @pytest.mark.asyncio
    async def test_sync_close(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        client = MagicMock()
        client.aclose = MagicMock(return_value=None)
        client.close = MagicMock(return_value=None)
        p._client = client

        await p.shutdown()
        # Один из aclose/close вызван
        assert client.aclose.called or client.close.called
        assert p._client is None

    @pytest.mark.asyncio
    async def test_async_close(self) -> None:
        """close() возвращает awaitable — await result."""
        p = FlagsmithProvider(environment_key="k")

        # Async close через aclose, возвращающий корутину
        async def async_aclose() -> None:
            return None

        client = MagicMock()
        client.aclose = async_aclose
        client.close = None
        p._client = client

        await p.shutdown()
        assert p._client is None

    @pytest.mark.asyncio
    async def test_close_exception_logged(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        client = MagicMock()
        client.aclose = MagicMock(side_effect=RuntimeError("err"))
        p._client = client

        with patch(
            "src.backend.core.feature_flags.flagsmith_provider._logger"
        ) as mock_logger:
            await p.shutdown()
            assert mock_logger.exception.called
            assert p._client is None

    @pytest.mark.asyncio
    async def test_no_close_method(self) -> None:
        """Клиент без aclose/close — skip, no error."""
        p = FlagsmithProvider(environment_key="k")
        client = MagicMock(spec=[])  # No aclose, no close
        p._client = client

        await p.shutdown()
        assert p._client is None


class TestGetClient:
    def test_no_key_returns_none(self) -> None:
        p = FlagsmithProvider()
        assert p._get_client() is None

    def test_lazy_init(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        assert p._client is None
        mock_http = MagicMock()
        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=mock_http,
        ) as mock_make:
            client = p._get_client()
            assert client is mock_http
            assert mock_make.called
            assert mock_make.call_args.kwargs["base_url"] == p.api_url
            assert mock_make.call_args.kwargs["headers"] == {"X-Environment-Key": "k"}
            assert mock_make.call_args.kwargs["plugin"] == (
                "core/feature_flags/flagsmith_provider"
            )

    def test_returns_existing(self) -> None:
        p = FlagsmithProvider(environment_key="k")
        existing = MagicMock()
        p._client = existing
        # Без patch — make_http_client не должен быть вызван
        assert p._get_client() is existing

    def test_import_error_raises_provider_error(self) -> None:
        """Если migration_helper unavailable — ProviderError."""
        p = FlagsmithProvider(environment_key="k")
        with patch.dict(sys.modules, {"src.backend.core.net.migration_helper": None}):
            with pytest.raises(ProviderError, match="migration_helper"):
                p._get_client()


class TestAllExports:
    def test_all(self) -> None:
        from src.backend.core.feature_flags import flagsmith_provider as m

        assert set(m.__all__) == {
            "EvaluationContext",
            "FlagsmithProvider",
            "ProviderError",
            "is_external_provider_enabled",
        }
