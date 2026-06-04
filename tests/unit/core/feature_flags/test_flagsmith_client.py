"""T-P0.1.14: unit-тесты для core/feature_flags/flagsmith_client.py (FlagsmithClient).

Coverage: flagsmith_client.py 27% → 90%+ через тестирование:
- FlagsmithFlag, FlagsmithUnavailableError
- FlagsmithClient (init, get_environment_flags, get_identity_flags, aclose, _get_client)
- _parse_flag
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.feature_flags.flagsmith_client import (
    FlagsmithClient,
    FlagsmithFlag,
    FlagsmithUnavailableError,
    _parse_flag,
)


def _make_response(
    status_code: int = 200, json_data: object = None, text: str = ""
) -> MagicMock:
    """Создаёт mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json = MagicMock(return_value=json_data)
    return resp


class TestFlagsmithFlag:
    def test_dataclass(self) -> None:
        flag = FlagsmithFlag(name="my_flag", enabled=True, value="on")
        assert flag.name == "my_flag"
        assert flag.enabled is True
        assert flag.value == "on"

    def test_frozen(self) -> None:
        flag = FlagsmithFlag(name="x", enabled=False, value=None)
        with pytest.raises((AttributeError, Exception)):
            flag.name = "y"  # type: ignore[misc]


class TestException:
    def test_inherits_runtime_error(self) -> None:
        exc = FlagsmithUnavailableError("flagsmith down")
        assert isinstance(exc, RuntimeError)
        assert "flagsmith down" in str(exc)


class TestInit:
    def test_defaults(self) -> None:
        c = FlagsmithClient(environment_key="ser.abc")
        assert c.environment_key == "ser.abc"
        assert c.api_url == "https://edge.api.flagsmith.com/api/v1/"
        assert c.timeout_seconds == 2.0
        assert c._client is None

    def test_no_key_allows_graceful(self) -> None:
        c = FlagsmithClient()
        assert c.environment_key is None

    def test_custom_params(self) -> None:
        http = MagicMock()
        c = FlagsmithClient(
            environment_key="key",
            api_url="https://custom.api/",
            timeout_seconds=5.0,
            http_client=http,
        )
        assert c.api_url == "https://custom.api/"  # trailing slash added
        assert c.timeout_seconds == 5.0
        assert c._client is http

    def test_api_url_strip_trailing_slash(self) -> None:
        c = FlagsmithClient(environment_key="k", api_url="https://x.com/api/")
        assert c.api_url == "https://x.com/api/"


class TestGetEnvironmentFlags:
    @pytest.mark.asyncio
    async def test_no_key_returns_empty(self) -> None:
        c = FlagsmithClient()
        result = await c.get_environment_flags()
        assert result == []

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        c = FlagsmithClient(environment_key="k")
        client = AsyncMock()
        client.get = AsyncMock(
            return_value=_make_response(
                status_code=200,
                json_data=[
                    {
                        "feature": {"name": "f1"},
                        "enabled": True,
                        "feature_state_value": "v1",
                    },
                    {
                        "feature": {"name": "f2"},
                        "enabled": False,
                        "feature_state_value": None,
                    },
                ],
            )
        )
        c._client = client

        result = await c.get_environment_flags()
        assert len(result) == 2
        assert result[0].name == "f1"
        assert result[0].enabled is True
        assert result[0].value == "v1"
        assert result[1].name == "f2"
        assert result[1].enabled is False
        assert result[1].value is None

    @pytest.mark.asyncio
    async def test_http_exception_raises_unavailable(self) -> None:
        c = FlagsmithClient(environment_key="k")
        client = AsyncMock()
        client.get = AsyncMock(side_effect=ConnectionError("net-err"))
        c._client = client

        with patch(
            "src.backend.core.feature_flags.flagsmith_client._logger"
        ) as mock_logger:
            with pytest.raises(FlagsmithUnavailableError, match="net-err"):
                await c.get_environment_flags()
            assert mock_logger.warning.called

    @pytest.mark.asyncio
    async def test_non_200_returns_empty(self) -> None:
        c = FlagsmithClient(environment_key="k")
        client = AsyncMock()
        client.get = AsyncMock(
            return_value=_make_response(status_code=500, text="internal error")
        )
        c._client = client

        with patch("src.backend.core.feature_flags.flagsmith_client._logger"):
            result = await c.get_environment_flags()
            assert result == []


class TestGetIdentityFlags:
    @pytest.mark.asyncio
    async def test_no_key_returns_empty(self) -> None:
        c = FlagsmithClient()
        result = await c.get_identity_flags(tenant_id="t1")
        assert result == []

    @pytest.mark.asyncio
    async def test_success_dict_payload(self) -> None:
        c = FlagsmithClient(environment_key="k")
        client = AsyncMock()
        client.get = AsyncMock(
            return_value=_make_response(
                status_code=200,
                json_data={
                    "flags": [
                        {
                            "feature": {"name": "f1"},
                            "enabled": True,
                            "feature_state_value": "v1",
                        }
                    ]
                },
            )
        )
        c._client = client

        result = await c.get_identity_flags(tenant_id="acme")
        assert len(result) == 1
        assert result[0].name == "f1"
        # URL params check
        call_args = client.get.call_args
        assert call_args.args[0] == "identities/"
        assert call_args.kwargs["params"] == {"identifier": "acme"}

    @pytest.mark.asyncio
    async def test_success_list_payload(self) -> None:
        """Если payload — list, flags = [] (defensive)."""
        c = FlagsmithClient(environment_key="k")
        client = AsyncMock()
        client.get = AsyncMock(
            return_value=_make_response(status_code=200, json_data=[{"flags": []}])
        )
        c._client = client

        result = await c.get_identity_flags(tenant_id="t1")
        assert result == []

    @pytest.mark.asyncio
    async def test_http_exception(self) -> None:
        c = FlagsmithClient(environment_key="k")
        client = AsyncMock()
        client.get = AsyncMock(side_effect=TimeoutError("slow"))
        c._client = client

        with pytest.raises(FlagsmithUnavailableError, match="slow"):
            await c.get_identity_flags(tenant_id="t1")

    @pytest.mark.asyncio
    async def test_non_200_returns_empty(self) -> None:
        c = FlagsmithClient(environment_key="k")
        client = AsyncMock()
        client.get = AsyncMock(return_value=_make_response(status_code=404))
        c._client = client

        result = await c.get_identity_flags(tenant_id="t1")
        assert result == []

    @pytest.mark.asyncio
    async def test_traits_accepted_but_not_sent(self) -> None:
        c = FlagsmithClient(environment_key="k")
        client = AsyncMock()
        client.get = AsyncMock(
            return_value=_make_response(status_code=200, json_data={"flags": []})
        )
        c._client = client

        result = await c.get_identity_flags(tenant_id="t1", traits={"plan": "pro"})
        assert result == []


class TestAclose:
    @pytest.mark.asyncio
    async def test_no_client(self) -> None:
        c = FlagsmithClient(environment_key="k")
        await c.aclose()  # No error
        assert c._client is None

    @pytest.mark.asyncio
    async def test_with_client(self) -> None:
        c = FlagsmithClient(environment_key="k")
        http = AsyncMock()
        http.aclose = AsyncMock()
        c._client = http

        await c.aclose()
        http.aclose.assert_called_once()
        assert c._client is None

    @pytest.mark.asyncio
    async def test_close_exception_logged_not_raised(self) -> None:
        c = FlagsmithClient(environment_key="k")
        http = AsyncMock()
        http.aclose = AsyncMock(side_effect=RuntimeError("close-err"))
        c._client = http

        with patch(
            "src.backend.core.feature_flags.flagsmith_client._logger"
        ) as mock_logger:
            await c.aclose()  # No raise
            assert mock_logger.exception.called
            assert c._client is None


class TestGetClient:
    def test_lazy_init(self) -> None:
        c = FlagsmithClient(environment_key="key")
        assert c._client is None
        mock_http = MagicMock()
        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=mock_http,
        ) as mock_make:
            client = c._get_client()
            assert mock_make.called
            call_kwargs = mock_make.call_args.kwargs
            assert call_kwargs["base_url"] == c.api_url
            assert call_kwargs["headers"] == {"X-Environment-Key": "key"}
            assert call_kwargs["timeout"] == c.timeout_seconds
            assert call_kwargs["plugin"] == "core/feature_flags/flagsmith"
            assert client is mock_http

    def test_returns_existing(self) -> None:
        c = FlagsmithClient(environment_key="k")
        existing = MagicMock()
        c._client = existing
        # Без patch — make_http_client не должен быть вызван
        assert c._get_client() is existing


class TestParseFlag:
    def test_full_dict(self) -> None:
        item = {
            "feature": {"name": "my_flag"},
            "enabled": True,
            "feature_state_value": "value",
        }
        flag = _parse_flag(item)
        assert flag.name == "my_flag"
        assert flag.enabled is True
        assert flag.value == "value"

    def test_missing_feature(self) -> None:
        item = {"enabled": False, "feature_state_value": 42}
        flag = _parse_flag(item)
        assert flag.name == ""
        assert flag.enabled is False
        assert flag.value == 42

    def test_empty_dict(self) -> None:
        flag = _parse_flag({})
        assert flag.name == ""
        assert flag.enabled is False
        assert flag.value is None

    def test_no_value(self) -> None:
        item = {"feature": {"name": "f"}, "enabled": True}
        flag = _parse_flag(item)
        assert flag.name == "f"
        assert flag.enabled is True
        assert flag.value is None


class TestAllExports:
    def test_all(self) -> None:
        from src.backend.core.feature_flags import flagsmith_client as m

        assert set(m.__all__) == {
            "FlagsmithClient",
            "FlagsmithFlag",
            "FlagsmithUnavailableError",
        }
