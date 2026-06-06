"""Coverage tests для BaseAPIClient base.py (Sprint 47 W3).

Targets: 79.1% → 100%.

Покрывает:
- set_token() — mutator для _token.
- _headers() — без token (default), с token (Bearer Authorization).
- HTTP method shortcuts: put, patch, delete.
- 401 → PermissionError (NOT retried).
- Text response (non-JSON content-type).
- 401 no-retry через _request (S46 W1 path policy не влияет).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient, get_base_client


def _make_context_mock(request_response: Any) -> MagicMock:
    """httpx.Client context manager mock — см. test_base_retry_policy.py."""
    m = MagicMock()
    m.request.return_value = request_response
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


class TestSetToken:
    """set_token mutator."""

    def test_set_token_to_value(self) -> None:
        c = BaseAPIClient()
        assert c._token is None
        c.set_token("jwt_xyz")
        assert c._token == "jwt_xyz"

    def test_set_token_to_none_clears(self) -> None:
        c = BaseAPIClient(token="jwt_initial")
        assert c._token == "jwt_initial"
        c.set_token(None)
        assert c._token is None

    def test_set_token_overwrites_previous(self) -> None:
        c = BaseAPIClient(token="jwt_old")
        c.set_token("jwt_new")
        assert c._token == "jwt_new"


class TestHeaders:
    """_headers() — собирает headers с/без auth token."""

    def test_headers_no_token(self) -> None:
        c = BaseAPIClient()
        h = c._headers()
        assert h["Content-Type"] == "application/json"
        assert h["Accept"] == "application/json"
        assert "Authorization" not in h

    def test_headers_with_token(self) -> None:
        c = BaseAPIClient(token="jwt_abc")
        h = c._headers()
        assert h["Authorization"] == "Bearer jwt_abc"

    def test_headers_after_set_token(self) -> None:
        c = BaseAPIClient()
        c.set_token("jwt_late")
        h = c._headers()
        assert h["Authorization"] == "Bearer jwt_late"


class TestHTTPMethodShortcuts:
    """put, patch, delete shortcuts — вызывают _request с правильным method."""

    def test_put_calls_request_with_put(self) -> None:
        c = BaseAPIClient()
        with _patch_request(c, return_value={"ok": True}) as req:
            result = c.put("/api/v1/x", json={"y": 1})
        assert result == {"ok": True}
        req.assert_called_once_with("PUT", "/api/v1/x", json={"y": 1})

    def test_patch_calls_request_with_patch(self) -> None:
        c = BaseAPIClient()
        with _patch_request(c, return_value={"ok": True}) as req:
            result = c.patch("/api/v1/x", json={"y": 2})
        assert result == {"ok": True}
        req.assert_called_once_with("PATCH", "/api/v1/x", json={"y": 2})

    def test_delete_calls_request_with_delete(self) -> None:
        c = BaseAPIClient()
        with _patch_request(c, return_value={"deleted": True}) as req:
            result = c.delete("/api/v1/x")
        assert result == {"deleted": True}
        req.assert_called_once_with("DELETE", "/api/v1/x")


class TestUnauthorizedHandling:
    """401 → PermissionError (NOT retried)."""

    def test_401_raises_permission_error(self) -> None:
        c = BaseAPIClient(max_retries=3)
        resp_401 = MagicMock(spec=httpx.Response)
        resp_401.status_code = 401
        resp_401.headers = {"content-type": "application/json"}
        resp_401.json.return_value = {"error": "unauthorized"}
        mock_client = _make_context_mock(resp_401)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(httpx, "Client", lambda *a, **kw: mock_client)
            with pytest.raises(PermissionError, match="Unauthorized"):
                c.get("/api/v1/x")
        # 401 is NOT retried — single call
        assert mock_client.request.call_count == 1

    def test_401_on_retry_path_also_raises(self) -> None:
        """``/api/v1/x`` (default path) + 401 → no retry, raise."""
        c = BaseAPIClient(max_retries=3)
        resp_401 = MagicMock(spec=httpx.Response)
        resp_401.status_code = 401
        resp_401.headers = {"content-type": "application/json"}
        resp_401.json.return_value = {"error": "unauthorized"}
        mock_client = _make_context_mock(resp_401)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(httpx, "Client", lambda *a, **kw: mock_client)
            with pytest.raises(PermissionError):
                c.get("/api/v1/x")
        assert mock_client.request.call_count == 1


class TestNonJsonResponse:
    """Response без application/json content-type → return text."""

    def test_text_response_returns_text(self) -> None:
        c = BaseAPIClient()
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {"content-type": "text/plain"}
        resp.text = "plain text response"
        resp.raise_for_status.return_value = None
        mock_client = _make_context_mock(resp)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(httpx, "Client", lambda *a, **kw: mock_client)
            result = c.get("/api/v1/text")
        assert result == "plain text response"

    def test_html_response_returns_html(self) -> None:
        c = BaseAPIClient()
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {"content-type": "text/html; charset=utf-8"}
        resp.text = "<html>...</html>"
        resp.raise_for_status.return_value = None
        mock_client = _make_context_mock(resp)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(httpx, "Client", lambda *a, **kw: mock_client)
            result = c.get("/")
        assert result == "<html>...</html>"

    def test_missing_content_type_returns_text(self) -> None:
        c = BaseAPIClient()
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {}  # no content-type
        resp.text = "no content type"
        resp.raise_for_status.return_value = None
        mock_client = _make_context_mock(resp)
        with pytest.MonkeyPatch.context() as m:
            m.setattr(httpx, "Client", lambda *a, **kw: mock_client)
            result = c.get("/raw")
        assert result == "no content type"


class TestGetBaseClient:
    """get_base_client() factory — singleton pattern."""

    def test_returns_base_api_client_instance(self) -> None:
        c = get_base_client()
        assert isinstance(c, BaseAPIClient)

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls return тот же instance (singleton)."""
        c1 = get_base_client()
        c2 = get_base_client()
        assert c1 is c2


# ============================================================
# Helpers
# ============================================================


def _patch_request(c: BaseAPIClient, return_value: Any) -> Any:
    """Context manager: patch BaseAPIClient._request с заданным return value."""
    from contextlib import contextmanager
    from unittest.mock import patch

    @contextmanager
    def cm() -> Any:
        with patch.object(c, "_request", return_value=return_value) as mock_req:
            yield mock_req

    return cm()
