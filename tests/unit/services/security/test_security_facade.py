"""Unit-тесты для SecurityFacade (S183)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.services.security.facade import SecurityFacade, get_security_facade


class TestSecurityFacadeJWTBlacklist:
    """Тесты JWT blacklist."""

    def test_blacklist_token(self) -> None:
        """Blacklist token добавляется в set."""
        facade = SecurityFacade()
        facade.blacklist_token("jti-123")
        assert facade.is_token_blacklisted("jti-123") is True

    def test_unblacklist_token(self) -> None:
        """Unblacklist удаляет token."""
        facade = SecurityFacade()
        facade.blacklist_token("jti-123")
        facade.unblacklist_token("jti-123")
        assert facade.is_token_blacklisted("jti-123") is False

    def test_clear_blacklist(self) -> None:
        """Clear удаляет все tokens."""
        facade = SecurityFacade()
        facade.blacklist_token("jti-1")
        facade.blacklist_token("jti-2")
        facade.clear_blacklist()
        assert facade.is_token_blacklisted("jti-1") is False
        assert facade.is_token_blacklisted("jti-2") is False


class TestSecurityFacadeSingleton:
    """Тесты singleton."""

    def test_get_security_facade_singleton(self) -> None:
        """get_security_facade возвращает один и тот же instance."""
        f1 = get_security_facade()
        f2 = get_security_facade()
        assert f1 is f2

    def test_facade_default_capability_check_is_none(self) -> None:
        """Default capability_check is None."""
        facade = SecurityFacade()
        assert facade._check is None
        assert facade._plugin == "extension"


class TestSecurityFacadeCapabilities:
    """Тесты capability checks."""

    @pytest.mark.asyncio
    async def test_check_capability_returns_bool(self) -> None:
        """check_capability возвращает bool."""
        facade = SecurityFacade()

        with patch(
            "src.backend.core.security.capabilities.CapabilityGate.check",
            return_value=True,
        ):
            result = await facade.check_capability("tenant-1", "ds.read", "user:42")
            assert result is True

    @pytest.mark.asyncio
    async def test_check_capability_handles_exception(self) -> None:
        """Exception в check → False (fail-safe)."""
        facade = SecurityFacade()

        with patch(
            "src.backend.core.security.capabilities.CapabilityGate.check",
            side_effect=RuntimeError("boom"),
        ):
            result = await facade.check_capability("tenant-1", "ds.read", "user:42")
            assert result is False


class TestSecurityFacadeSignatures:
    """Тесты signature verification (re-export)."""

    def test_verify_signature_delegates(self) -> None:
        """verify_signature делегирует к infrastructure.security.signatures."""
        facade = SecurityFacade()

        with patch(
            "src.backend.infrastructure.security.signatures.verify_signature",
            return_value=True,
        ) as mock_verify:
            result = facade.verify_signature(
                payload=b"data",
                signature="abc123",
                timestamp=1234567890,
                secret="secret",
            )
            assert result is True
            mock_verify.assert_called_once()


class TestSecurityFacadeCapabilityAssert:
    """Тесты capability-check на других операциях."""

    def test_assert_no_check_skipped(self) -> None:
        """_assert без check callback — no-op."""
        facade = SecurityFacade()  # no capability_check
        facade._assert("any.action", "any.resource")  # no error

    def test_assert_with_check_called(self) -> None:
        """_assert с check callback — вызывает его."""
        mock_check = MagicMock()
        facade = SecurityFacade(capability_check=mock_check, plugin="my_plugin")

        facade._assert("test.action", "test.resource")

        mock_check.assert_called_once_with("my_plugin", "test.action", "test.resource")
