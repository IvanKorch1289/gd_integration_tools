"""Unit tests for S172 M1.1 WS auth facade.

Tests:
- ``extract_credential`` semantics (subprotocol / cookie / query / no credential).
- ``WSAuthenticator.authenticate_jwt`` happy path + invalid token.
- ``WSAuthenticator.authenticate_via_facade`` routing.
- Backward-compat: existing ``authenticate(token)`` API-key path unchanged.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.backend.entrypoints.websocket.ws_auth import (
    WS_AUTH_COOKIE_NAME,
    WSAuthenticator,
    WSAuthError,
    WSCredential,
    WSSession,
    extract_credential,
    get_ws_authenticator,
)


class TestExtractCredential:
    """Tests for :func:`extract_credential` — WS handshake credential routing."""

    def test_no_sources_returns_none(self) -> None:
        assert extract_credential(None, None, None) is None

    def test_subprotocol_jwt_prefix(self) -> None:
        cred = extract_credential("jwt.eyJhbGciOiJIUzI1NiJ9.payload.sig")
        assert cred is not None
        assert cred.method == "jwt"
        assert cred.source == "subprotocol"
        assert cred.token == "eyJhbGciOiJIUzI1NiJ9.payload.sig"

    def test_subprotocol_apikey_prefix(self) -> None:
        cred = extract_credential("apikey.sk_test_abc123")
        assert cred is not None
        assert cred.method == "api_key"
        assert cred.source == "subprotocol"
        assert cred.token == "sk_test_abc123"

    def test_subprotocol_comma_separated(self) -> None:
        # Header может выглядеть как "chat, jwt.<token>".
        cred = extract_credential("chat, jwt.abc.def.ghi")
        assert cred is not None
        assert cred.method == "jwt"
        assert cred.token == "abc.def.ghi"

    def test_subprotocol_priority_over_cookie(self) -> None:
        cred = extract_credential(
            "jwt.sub_token",
            cookies={WS_AUTH_COOKIE_NAME: "cookie_value"},
        )
        assert cred is not None
        assert cred.source == "subprotocol"
        assert cred.token == "sub_token"

    def test_cookie_jwt_format(self) -> None:
        cred = extract_credential(None, cookies={WS_AUTH_COOKIE_NAME: "aaa.bbb.ccc"})
        assert cred is not None
        assert cred.method == "jwt"
        assert cred.source == "cookie"

    def test_cookie_apikey_format(self) -> None:
        cred = extract_credential(
            None,
            cookies={WS_AUTH_COOKIE_NAME: "sk_live_xyz"},
        )
        assert cred is not None
        assert cred.method == "api_key"
        assert cred.source == "cookie"

    def test_cookies_disabled_returns_none(self) -> None:
        cred = extract_credential(
            None,
            cookies={WS_AUTH_COOKIE_NAME: "abc"},
            allow_cookies=False,
        )
        assert cred is None

    def test_query_disabled_by_default(self) -> None:
        cred = extract_credential(None, None, query_token="abc")
        assert cred is None

    def test_query_when_explicitly_enabled(self) -> None:
        cred = extract_credential(None, None, query_token="abc", allow_query=True)
        assert cred is not None
        assert cred.source == "query"
        assert cred.method == "api_key"
        assert cred.token == "abc"

    def test_unknown_subprotocol_prefix_ignored(self) -> None:
        # Subprotocol "chat" без префикса jwt./apikey. — не credential.
        cred = extract_credential("chat")
        assert cred is None

    def test_strips_whitespace(self) -> None:
        cred = extract_credential("  jwt.spaced_token  ")
        assert cred is not None
        assert cred.token == "spaced_token"


class TestWSAuthenticatorJWT:
    """Tests for :meth:`WSAuthenticator.authenticate_jwt`."""

    @pytest.fixture
    def authenticator(self) -> WSAuthenticator:
        return WSAuthenticator()

    @pytest.mark.asyncio
    async def test_missing_token_raises(self, authenticator: WSAuthenticator) -> None:
        with pytest.raises(WSAuthError, match="Missing JWT token"):
            await authenticator.authenticate_jwt("")

    @pytest.mark.asyncio
    async def test_jwt_decode_failure_raises(
        self, authenticator: WSAuthenticator
    ) -> None:
        """Backend rejects malformed/expired token → WSAuthError."""

        class _FakeBackend:
            def decode(self, token: str) -> dict[str, object]:
                raise RuntimeError("invalid signature")

        with patch(
            "src.backend.core.auth.jwt_backend.JwtBackend",
            _FakeBackend,
        ):
            with pytest.raises(WSAuthError, match="JWT"):
                await authenticator.authenticate_jwt("malformed.token.here")

    @pytest.mark.asyncio
    async def test_jwt_backend_unavailable_raises(
        self, authenticator: WSAuthenticator, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Имитация отсутствующего joserfc / AuthError при ImportError."""

        # Подменяем import на стороне jwt_backend: он бросит ImportError.
        from src.backend.core.auth import jwt_backend as jbmod

        # Симулируем ImportError на строке `from joserfc import jwt`.
        original_import = jbmod.__class__.__name__  # noqa: F841 (no-op, just to keep)

        # Простой подход: попросить authenticate_jwt и убедиться, что WSAuthError поднимается
        # при ImportError на joserfc.
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "joserfc" or name.startswith("joserfc."):
                raise ImportError("simulated missing joserfc")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(WSAuthError):
            await authenticator.authenticate_jwt("any.token.value")


class TestWSAuthenticatorFacade:
    """Tests for :meth:`WSAuthenticator.authenticate_via_facade`."""

    @pytest.fixture
    def authenticator(self) -> WSAuthenticator:
        return WSAuthenticator()

    @pytest.mark.asyncio
    async def test_routes_jwt_method(
        self, authenticator: WSAuthenticator
    ) -> None:
        cred = WSCredential(token="dummy.jwt.token", method="jwt", source="subprotocol")
        # backend отсутствует → WSAuthError (test passes whichever backend raises).
        with pytest.raises(WSAuthError):
            await authenticator.authenticate_via_facade(cred)

    @pytest.mark.asyncio
    async def test_routes_api_key_method(
        self, authenticator: WSAuthenticator
    ) -> None:
        """api_key path — backward-compat через authenticate()."""

        cred = WSCredential(
            token="Bearer valid-token",
            method="api_key",
            source="subprotocol",
        )
        mock_mgr = AsyncMock()
        mock_mgr.validate.return_value = {
            "hash": "abc123",
            "client_id": "client1",
            "is_admin": False,
        }
        with patch(
            "src.backend.core.di.providers.get_api_key_manager_provider",
            return_value=mock_mgr,
        ):
            session = await authenticator.authenticate_via_facade(cred)
        assert session.auth_source == "api_key"
        assert session.client_id == "client1"

    @pytest.mark.asyncio
    async def test_routes_api_key_cookie_sets_auth_source(
        self, authenticator: WSAuthenticator
    ) -> None:
        cred = WSCredential(
            token="my-api-key",
            method="api_key",
            source="cookie",
        )
        mock_mgr = AsyncMock()
        mock_mgr.validate.return_value = {
            "hash": "abc123",
            "client_id": "client1",
            "is_admin": False,
        }
        with patch(
            "src.backend.core.di.providers.get_api_key_manager_provider",
            return_value=mock_mgr,
        ):
            session = await authenticator.authenticate_via_facade(cred)
        assert session.auth_source == "cookie_apikey"


class TestWSSessionBackwardCompat:
    """WSSession backward-compat: new fields default-safe для старого кода."""

    def test_default_auth_source(self) -> None:
        session = WSSession(client_id="c", api_key_hash="h")
        assert session.auth_source == "api_key"
        assert session.principal == ""

    def test_explicit_auth_source(self) -> None:
        session = WSSession(
            client_id="c",
            api_key_hash="h",
            auth_source="jwt",
            principal="user@example.com",
        )
        assert session.auth_source == "jwt"
        assert session.principal == "user@example.com"


class TestGetWSAuthenticatorSingleton:
    def test_returns_same_instance(self) -> None:
        a1 = get_ws_authenticator()
        a2 = get_ws_authenticator()
        assert a1 is a2
