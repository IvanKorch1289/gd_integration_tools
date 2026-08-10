"""Tests для AuthFacade (S185) — production-ready state.

Coverage:
- verify_request для JWT (success/failure)
- verify_request для API key (success/failure)
- check_permission (admin bypass, capability match)
- get_tenant
- _is_blacklisted (JWT blacklist integration)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.auth.facade import AuthFacade


class TestAuthFacadeJWT:
    """Тесты AuthFacade JWT verification."""

    @pytest.mark.asyncio
    async def test_verify_jwt_success(self) -> None:
        """Успешная JWT verification."""
        facade = AuthFacade()
        mock_claims = {
            "sub": "user:42",
            "tenant_id": "tenant_1",
            "groups": ["admin"],
            "capabilities": ["ds.read"],
        }

        with patch.object(facade.jwt, "decode", return_value=mock_claims):
            result = await facade.verify_request("valid.jwt.token", method="jwt")

        assert result.is_authenticated is True
        assert result.method == "jwt"
        assert result.subject == "user:42"
        assert result.tenant_id == "tenant_1"
        assert "admin" in result.groups
        assert "ds.read" in result.capabilities

    @pytest.mark.asyncio
    async def test_verify_jwt_invalid_returns_unauthenticated(self) -> None:
        """Invalid JWT → unauthenticated."""
        facade = AuthFacade()

        with patch.object(
            facade.jwt,
            "decode",
            side_effect=Exception("invalid signature"),
        ):
            result = await facade.verify_request("invalid.jwt.token", method="jwt")

        assert result.is_authenticated is False
        assert "error" in result.metadata

    @pytest.mark.asyncio
    async def test_verify_jwt_blacklisted(self) -> None:
        """Blacklisted JWT (jti в blacklist) → unauthenticated."""
        facade = AuthFacade()
        mock_claims = {
            "sub": "user:42",
            "jti": "jti-blacklisted-123",
        }

        with patch.object(facade.jwt, "decode", return_value=mock_claims):
            with patch.object(
                facade,
                "_is_blacklisted",
                return_value=True,
            ):
                result = await facade.verify_request("blacklisted.jwt", method="jwt")

        assert result.is_authenticated is False
        assert result.metadata.get("error") == "token_revoked"


class TestAuthFacadeAPIKey:
    """Тесты AuthFacade API key verification (S183 fix)."""

    @pytest.mark.asyncio
    async def test_verify_api_key_invalid_format(self) -> None:
        """API key без префикса 'ak_' → unauthenticated."""
        facade = AuthFacade()
        result = await facade.verify_request("not-an-api-key", method="api_key")
        assert result.is_authenticated is False

    @pytest.mark.asyncio
    async def test_verify_api_key_invalid_segments(self) -> None:
        """API key без правильных сегментов → unauthenticated."""
        facade = AuthFacade()
        result = await facade.verify_request("ak_invalid", method="api_key")
        assert result.is_authenticated is False


class TestAuthFacadeSAML:
    """SAML verification must use the configured ACS flow."""

    @pytest.mark.asyncio
    async def test_raw_assertion_fails_closed(self) -> None:
        facade = AuthFacade()

        result = await facade.verify_request("raw-assertion", method="saml")

        assert result.is_authenticated is False
        # Cycle 94 L10: subset check (same fix as Cycle 92) — production
        # metadata includes assertion_len debug info.
        assert result.metadata["error"] == "saml_requires_acs_flow"
        assert "assertion_len" in result.metadata


class TestAuthFacadePermissions:
    """Тесты check_permission."""

    def test_check_permission_unauthenticated(self) -> None:
        """Unauthenticated → False."""
        facade = AuthFacade()
        from src.backend.core.auth.facade import AuthResult

        auth = AuthResult(is_authenticated=False)
        assert facade.check_permission(auth, "any.capability") is False

    def test_check_permission_admin_bypass(self) -> None:
        """SUPER_ADMIN role → True для любой capability."""
        facade = AuthFacade()
        from src.backend.core.auth.facade import AuthResult

        # Cycle 91 L10: production calls extract_admin_roles(auth) which
        # reads auth.metadata. AuthResult (not AuthContext) is the correct
        # type — it has is_authenticated attribute that check_permission
        # checks first. Per S189+ fix: AdminRole enum, not "admin" string.
        auth = AuthResult(
            is_authenticated=True,
            method="jwt",
            subject="u1",
            metadata={"admin_roles": ["super_admin"]},
        )
        assert facade.check_permission(auth, "any.capability") is True

    def test_check_permission_specific_capability_match(self) -> None:
        """Capability в списке → True."""
        facade = AuthFacade()
        from src.backend.core.auth.facade import AuthResult

        auth = AuthResult(
            is_authenticated=True,
            capabilities=["ds.read", "ds.write"],
        )
        assert facade.check_permission(auth, "ds.read") is True

    def test_check_permission_no_match(self) -> None:
        """Capability не в списке → False."""
        facade = AuthFacade()
        from src.backend.core.auth.facade import AuthResult

        auth = AuthResult(
            is_authenticated=True,
            capabilities=["ds.read"],
        )
        assert facade.check_permission(auth, "ds.write") is False


class TestAuthFacadeHelpers:
    """Тесты вспомогательных методов."""

    def test_get_tenant_returns_tenant_id(self) -> None:
        """get_tenant возвращает tenant_id из AuthResult."""
        facade = AuthFacade()
        from src.backend.core.auth.facade import AuthResult

        auth = AuthResult(is_authenticated=True, tenant_id="tenant_42")
        with patch(
            "src.backend.core.auth.auth_context_helpers.extract_tenant_id",
            return_value="tenant_42",
        ):
            assert facade.get_tenant(auth) == "tenant_42"

    def test_get_tenant_returns_none_for_no_tenant(self) -> None:
        """get_tenant возвращает None если нет tenant."""
        facade = AuthFacade()
        from src.backend.core.auth.facade import AuthResult

        auth = AuthResult(is_authenticated=True, tenant_id=None)
        with patch(
            "src.backend.core.auth.auth_context_helpers.extract_tenant_id",
            return_value=None,
        ):
            assert facade.get_tenant(auth) is None

    def test_is_blacklisted_uses_security_facade(self) -> None:
        """_is_blacklisted проверяет через SecurityFacade.is_token_blacklisted."""
        facade = AuthFacade()

        with patch(
            "src.backend.services.security.facade.get_security_facade"
        ) as mock_get_facade:
            mock_facade = MagicMock()
            mock_facade.is_token_blacklisted = AsyncMock(return_value=True)
            mock_get_facade.return_value = mock_facade

            # Cycle 89 L10: await the async call.
            import asyncio

            result = asyncio.run(facade._is_blacklisted("jti-123"))
            assert result is True
            mock_facade.is_token_blacklisted.assert_called_once_with("jti-123")

    def test_is_blacklisted_returns_false_on_exception(self) -> None:
        """_is_blacklisted returns False при ошибке SecurityFacade."""
        facade = AuthFacade()

        with patch(
            "src.backend.services.security.facade.get_security_facade",
            side_effect=RuntimeError("boom"),
        ):
            # Cycle 88 L10: _is_blacklisted is async — was never awaited.
            # Production is FAIL-CLOSED on Redis failure (treats token as
            # revoked). Test updated to match production semantics — the
            # old assertion was fail-OPEN which would be a security bug.
            import asyncio

            result = asyncio.run(facade._is_blacklisted("jti-123"))
            assert result is True  # fail-closed: Redis down → assume revoked


class TestAuthFacadeTokenIssuance:
    """S31 Task 4: JWT issuance + revocation."""

    def test_issue_token_returns_jwt(self) -> None:
        """issue_token делегирует в jwt_backend.encode и возвращает (token, expires_in)."""
        facade = AuthFacade()
        mock_token = "eyJ.encoded.jwt"
        with patch.object(
            facade.jwt,
            "encode",
            return_value=(mock_token, 3600),
        ) as mock_encode:
            token, expires = facade.issue_token(
                subject="user:1",
                tenant_id="tenant_a",
                groups=["g1"],
                capabilities=["c1"],
            )

        assert token == mock_token
        assert expires == 3600
        # Verify claims merged correctly
        call_kwargs = mock_encode.call_args.kwargs
        assert call_kwargs["subject"] == "user:1"
        assert call_kwargs["expires_in"] == 3600
        assert call_kwargs["claims"]["tenant_id"] == "tenant_a"
        assert call_kwargs["claims"]["groups"] == ["g1"]
        assert call_kwargs["claims"]["capabilities"] == ["c1"]
        assert call_kwargs["claims"]["auth_method"] == "jwt"

    def test_issue_token_rejects_empty_subject(self) -> None:
        """issue_token raises ValueError на пустой subject."""
        facade = AuthFacade()
        with pytest.raises(ValueError, match="subject must be non-empty"):
            facade.issue_token(subject="")

    def test_issue_token_wraps_jwt_errors(self) -> None:
        """issue_token wraps encode errors в RuntimeError."""
        facade = AuthFacade()
        with patch.object(
            facade.jwt,
            "encode",
            side_effect=ValueError("missing secret"),
        ), pytest.raises(RuntimeError, match="issue_token failed"):
            facade.issue_token(subject="user:1")

    @pytest.mark.asyncio
    async def test_revoke_token_success(self) -> None:
        """revoke_token → SecurityFacade.blacklist_token."""
        facade = AuthFacade()
        with patch(
            "src.backend.services.security.facade.get_security_facade"
        ) as mock_get_facade:
            mock_sec_facade = MagicMock()
            mock_sec_facade.blacklist_token = MagicMock(
                return_value=None  # sync — could be sync or async
            )
            # Make it return a coroutine to support await
            async def _awaitable_blacklist(jti: str) -> bool:
                return True

            mock_sec_facade.blacklist_token = _awaitable_blacklist
            mock_get_facade.return_value = mock_sec_facade

            result = await facade.revoke_token("jti-revoke-1")
            assert result is True

    @pytest.mark.asyncio
    async def test_revoke_token_rejects_empty_jti(self) -> None:
        """revoke_token raises ValueError на пустой jti."""
        facade = AuthFacade()
        with pytest.raises(ValueError, match="jti must be non-empty"):
            await facade.revoke_token("")

    @pytest.mark.asyncio
    async def test_revoke_token_propagates_errors(self) -> None:
        """revoke_token raises RuntimeError при ошибке SecurityFacade."""
        facade = AuthFacade()
        with patch(
            "src.backend.services.security.facade.get_security_facade",
            side_effect=RuntimeError("redis down"),
        ), pytest.raises(RuntimeError, match="revoke_token failed"):
            await facade.revoke_token("jti-1")


class TestAuthFacadeSAMLDevMode:
    """S31 Task 4: SAML verification с config gate."""

    @pytest.mark.asyncio
    async def test_saml_dev_mode_disabled_fails_closed(self) -> None:
        """Dev-mode flag off → fail-closed (no real ACS)."""
        facade = AuthFacade()
        with patch(
            "src.backend.core.config.features.feature_flags",
            MagicMock(saml_sp_initiated_enabled=False),
        ):
            result = await facade.verify_saml_assertion("some.assertion")
        assert result.is_authenticated is False
        assert result.metadata["error"] == "saml_requires_acs_flow"

    @pytest.mark.asyncio
    async def test_saml_dev_mode_enabled_valid_assertion(self) -> None:
        """Dev-mode flag on + valid base64 assertion → authenticated."""
        import base64

        facade = AuthFacade()
        xml = (
            '<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">'
            "<saml:Issuer>https://idp.example.com</saml:Issuer>"
            "<saml:Subject><saml:NameID>user:ldap1</saml:NameID></saml:Subject>"
            "</saml:Assertion>"
        )
        assertion_b64 = base64.b64encode(xml.encode()).decode()

        with patch(
            "src.backend.core.config.features.feature_flags",
            MagicMock(saml_sp_initiated_enabled=True),
        ):
            result = await facade.verify_saml_assertion(assertion_b64)
        assert result.is_authenticated is True
        assert result.subject == "user:ldap1"
        assert result.method == "saml"
        assert result.metadata["issuer"] == "https://idp.example.com"

    @pytest.mark.asyncio
    async def test_saml_empty_assertion_fails(self) -> None:
        """Empty assertion → unauthenticated."""
        facade = AuthFacade()
        with patch(
            "src.backend.core.config.features.feature_flags",
            MagicMock(saml_sp_initiated_enabled=True),
        ):
            result = await facade.verify_saml_assertion("")
        assert result.is_authenticated is False
        assert result.metadata["error"] == "saml_empty_assertion"

    @pytest.mark.asyncio
    async def test_saml_issuer_mismatch(self) -> None:
        """expected_issuer set + actual issuer different → unauthenticated."""
        import base64

        facade = AuthFacade()
        xml = (
            '<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">'
            "<saml:Issuer>https://wrong.example.com</saml:Issuer>"
            "<saml:Subject><saml:NameID>user</saml:NameID></saml:Subject>"
            "</saml:Assertion>"
        )
        assertion_b64 = base64.b64encode(xml.encode()).decode()

        with patch(
            "src.backend.core.config.features.feature_flags",
            MagicMock(saml_sp_initiated_enabled=True),
        ):
            result = await facade.verify_saml_assertion(
                assertion_b64,
                expected_issuer="https://idp.example.com",
            )
        assert result.is_authenticated is False
        assert result.metadata["error"] == "saml_issuer_mismatch"


class TestAuthFacadeLDAP:
    """S31 Task 4: LDAP credential verification."""

    @pytest.mark.asyncio
    async def test_ldap_empty_credentials(self) -> None:
        """Empty username/password → unauthenticated."""
        facade = AuthFacade()
        result = await facade.verify_ldap_credentials("", "")
        assert result.is_authenticated is False
        assert result.metadata["error"] == "ldap_empty_credentials"

    @pytest.mark.asyncio
    async def test_ldap_bind_success(self) -> None:
        """Successful LDAP bind → authenticated."""
        from unittest.mock import AsyncMock, MagicMock

        facade = AuthFacade()
        mock_client = MagicMock()
        mock_client.bind = AsyncMock(return_value=True)
        with patch(
            "src.backend.core.auth.ldap_client_factory.get_ad_client",
            return_value=mock_client,
        ):
            result = await facade.verify_ldap_credentials(
                "alice",
                "secret",
                tenant_id="tenant_a",
            )
        assert result.is_authenticated is True
        assert result.subject == "alice"
        assert result.tenant_id == "tenant_a"
        assert result.method == "ldap"
        mock_client.bind.assert_awaited_once_with("alice", "secret")

    @pytest.mark.asyncio
    async def test_ldap_bind_failed(self) -> None:
        """Failed LDAP bind → unauthenticated."""
        from unittest.mock import AsyncMock, MagicMock

        facade = AuthFacade()
        mock_client = MagicMock()
        mock_client.bind = AsyncMock(return_value=False)
        with patch(
            "src.backend.core.auth.ldap_client_factory.get_ad_client",
            return_value=mock_client,
        ):
            result = await facade.verify_ldap_credentials("alice", "wrong")
        assert result.is_authenticated is False
        assert result.metadata["error"] == "ldap_bind_failed"
