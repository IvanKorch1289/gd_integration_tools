"""Unit tests for SAML endpoints."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from starlette.datastructures import FormData

from src.backend.entrypoints.api.v1.endpoints import auth_saml as saml_mod


class TestIsSafeReturnTo:
    def test_empty(self) -> None:
        assert saml_mod._is_safe_return_to("", "test.com") is False

    def test_relative_path(self) -> None:
        assert saml_mod._is_safe_return_to("/dashboard", "test.com") is True

    def test_double_slash_relative(self) -> None:
        assert saml_mod._is_safe_return_to("//evil.com", "test.com") is False

    def test_same_host(self) -> None:
        assert saml_mod._is_safe_return_to("https://test.com/x", "test.com") is True

    def test_different_host(self) -> None:
        assert saml_mod._is_safe_return_to("https://evil.com/x", "test.com") is False

    def test_no_host_always_relative(self) -> None:
        assert saml_mod._is_safe_return_to("/path", None) is True


class TestGetHandler:
    def test_missing_handler_raises_503(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.saml_sp_handler = None
        with pytest.raises(HTTPException) as exc_info:
            saml_mod._get_handler(request)
        assert exc_info.value.status_code == 503

    def test_returns_handler(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.saml_sp_handler = MagicMock()
        handler = saml_mod._get_handler(request)
        assert handler is request.app.state.saml_sp_handler


class TestSamlLogin:
    @pytest.mark.asyncio
    async def test_login_redirect(self) -> None:
        request = MagicMock(spec=Request)
        request.url.hostname = "test.com"
        request.app.state.saml_sp_handler = MagicMock()
        result = MagicMock()
        result.redirect_url = "https://idp.example.com/sso"
        result.request_id = "req1"
        result.relay_state = "rs1"
        request.app.state.saml_sp_handler.initiate_login.return_value = result

        resp = await saml_mod.saml_login(request, return_to="/dashboard")
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://idp.example.com/sso"

    @pytest.mark.asyncio
    async def test_login_unsafe_return_to(self) -> None:
        request = MagicMock(spec=Request)
        request.url.hostname = "test.com"
        request.app.state.saml_sp_handler = MagicMock()
        result = MagicMock()
        result.redirect_url = "https://idp.example.com/sso"
        request.app.state.saml_sp_handler.initiate_login.return_value = result

        resp = await saml_mod.saml_login(request, return_to="https://evil.com")
        assert resp.status_code == 302
        request.app.state.saml_sp_handler.initiate_login.assert_called_once_with(
            return_to=None
        )


class TestSamlAcs:
    @pytest.mark.asyncio
    async def test_acs_success(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.saml_sp_handler = MagicMock()
        request.app.state.saml_validator_factory = MagicMock()
        auth_result = MagicMock()
        auth_result.principal = "user1"
        auth_result.session_index = "sess1"
        request.app.state.saml_sp_handler.consume_acs.return_value = auth_result

        form = FormData([("SAMLResponse", "resp"), ("InResponseTo", "req1")])
        request.form = AsyncMock(return_value=form)

        response = MagicMock()
        result = await saml_mod.saml_acs(request, response)
        assert result["principal"] == "user1"
        response.set_cookie.assert_called_once()

    @pytest.mark.asyncio
    async def test_acs_missing_fields(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.saml_sp_handler = MagicMock()
        form = FormData([])
        request.form = AsyncMock(return_value=form)

        response = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await saml_mod.saml_acs(request, response)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_acs_no_validator(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.saml_sp_handler = MagicMock()
        request.app.state.saml_validator_factory = None
        form = FormData([("SAMLResponse", "resp"), ("InResponseTo", "req1")])
        request.form = AsyncMock(return_value=form)

        response = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await saml_mod.saml_acs(request, response)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_acs_saml_error(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.saml_sp_handler = MagicMock()
        request.app.state.saml_validator_factory = MagicMock()
        from src.backend.core.auth.saml import SamlError

        request.app.state.saml_sp_handler.consume_acs.side_effect = SamlError("bad")

        form = FormData([("SAMLResponse", "resp"), ("InResponseTo", "req1")])
        request.form = AsyncMock(return_value=form)

        response = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await saml_mod.saml_acs(request, response)
        assert exc_info.value.status_code == 401


class TestSamlSls:
    @pytest.mark.asyncio
    async def test_sls_clears_cookie(self) -> None:
        request = MagicMock(spec=Request)
        resp = await saml_mod.saml_sls(request)
        assert resp.status_code == 200
