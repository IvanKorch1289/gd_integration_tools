"""Unit tests for src.backend.services.rpa.desktop_rpa_client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.rpa.desktop_rpa_client import (
    DesktopRpaClient,
    DesktopRpaError,
)


class TestInit:
    def test_defaults(self) -> None:
        client = DesktopRpaClient("http://worker:9001/")
        assert client._base_url == "http://worker:9001"
        assert client._api_key is None
        assert client._timeout == 30.0

    def test_custom(self) -> None:
        client = DesktopRpaClient("http://worker:9001", api_key="k", timeout=5.0)
        assert client._api_key == "k"
        assert client._timeout == 5.0


@pytest.mark.asyncio
class TestExecute:
    async def test_success(self) -> None:
        client = DesktopRpaClient("http://w", api_key="k")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_http), __aexit__=AsyncMock()
            ),
        ):
            result = await client.execute("click", {"x": 1})
        assert result == {"ok": True}
        mock_http.post.assert_awaited_once_with(
            "http://w/rpa/click", json={"x": 1}, headers={"X-API-Key": "k"}
        )

    async def test_unsupported_action(self) -> None:
        client = DesktopRpaClient("http://w")
        with pytest.raises(DesktopRpaError, match="Unsupported action"):
            await client.execute("fly", {})

    async def test_transport_error(self) -> None:
        import httpx

        client = DesktopRpaClient("http://w")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.HTTPError("net"))
        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_http),
                __aexit__=AsyncMock(return_value=None),
            ),
        ):
            with pytest.raises(DesktopRpaError, match="transport error"):
                await client.execute("click", {})

    async def test_503(self) -> None:
        client = DesktopRpaClient("http://w")
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_http), __aexit__=AsyncMock()
            ),
        ):
            with pytest.raises(DesktopRpaError, match="503"):
                await client.execute("click", {})

    async def test_400(self) -> None:
        client = DesktopRpaClient("http://w")
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "bad request"
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_http), __aexit__=AsyncMock()
            ),
        ):
            with pytest.raises(DesktopRpaError, match="400"):
                await client.execute("click", {})

    async def test_no_api_key(self) -> None:
        client = DesktopRpaClient("http://w")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_http), __aexit__=AsyncMock()
            ),
        ):
            await client.execute("type", {"text": "hi"})
        assert mock_http.post.await_args[1]["headers"] == {}
