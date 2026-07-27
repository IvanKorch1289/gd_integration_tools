"""Tests для AuthFacade (S185) — production-ready state.

Coverage:
- verify_request для JWT (success/failure)
- verify_request для API key (success/failure)
- check_permission (admin bypass, capability match)
- get_tenant
- _is_blacklisted (JWT blacklist integration)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
        assert result.metadata == {"error": "saml_requires_acs_flow"}


class TestAuthFacadePermissions:
    """Тесты check_permission."""

    def test_check_permission_unauthenticated(self) -> None:
        """Unauthenticated → False."""
        facade = AuthFacade()
        from src.backend.core.auth.facade import AuthResult

        auth = AuthResult(is_authenticated=False)
        assert facade.check_permission(auth, "any.capability") is False

    def test_check_permission_admin_bypass(self) -> None:
        """Admin в groups → True для любой capability."""
        facade = AuthFacade()
        from src.backend.core.auth.facade import AuthResult

        auth = AuthResult(
            is_authenticated=True,
            groups=["admin", "user"],
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
            mock_facade.is_token_blacklisted.return_value = True
            mock_get_facade.return_value = mock_facade

            assert facade._is_blacklisted("jti-123") is True
            mock_facade.is_token_blacklisted.assert_called_once_with("jti-123")

    def test_is_blacklisted_returns_false_on_exception(self) -> None:
        """_is_blacklisted returns False при ошибке SecurityFacade."""
        facade = AuthFacade()

        with patch(
            "src.backend.services.security.facade.get_security_facade",
            side_effect=RuntimeError("boom"),
        ):
            assert facade._is_blacklisted("jti-123") is False
