"""Coverage tests для connector_auth (Sprint 5 continuation, 2026-08-17).

TDD: tests для security-critical connector authorization decorator.
Реальный code в src/backend/core/security/connector_auth.py.

Coverage targets:
- ConnectorAuthError: PermissionError subclass
- require_capability: fail-closed on facade unavailable,
  fail-closed on facade exception, deny on policy denial, allow on pass
- check_source_capability: bool return value, fail-closed on facade unavailable
- Edge cases: empty capability name → ValueError
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.security.connector_auth import (
    ConnectorAuthError,
    check_source_capability,
    require_capability,
)


class TestConnectorAuthError:
    """ConnectorAuthError — exception contract."""

    def test_is_permission_error_subclass(self) -> None:
        """ConnectorAuthError MUST be subclass of PermissionError.

        FastAPI middleware should catch generically."""
        assert issubclass(ConnectorAuthError, PermissionError)


class TestRequireCapabilityValidation:
    """require_capability — input validation."""

    def test_empty_capability_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            require_capability("")

    def test_non_string_capability_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            require_capability(None)  # type: ignore[arg-type]


class TestRequireCapabilityFailClosed:
    """require_capability MUST fail-closed when facade unavailable."""

    @pytest.mark.asyncio
    async def test_facade_unavailable_raises_connector_auth_error(self) -> None:
        """Если AuthorizationFacade недоступен — fail-closed (deny)."""

        @require_capability("test.capability")
        async def my_func() -> str:
            return "should not reach"

        # Patch via sys.modules to simulate facade unavailable
        import sys
        original_module = sys.modules.pop(
            "src.backend.services.authorization.facade", None,
        )
        sys.modules["src.backend.services.authorization.facade"] = None  # Force ImportError
        try:
            with pytest.raises(ConnectorAuthError, match="facade unavailable"):
                await my_func()
        finally:
            # Restore
            if original_module is not None:
                sys.modules["src.backend.services.authorization.facade"] = original_module
            else:
                sys.modules.pop("src.backend.services.authorization.facade", None)


class TestRequireCapabilityPolicyDecision:
    """require_capability — policy decision delegation."""

    @pytest.mark.asyncio
    async def test_allowed_capability_passes_through(self) -> None:
        """Если facade разрешает — функция выполняется нормально."""

        @require_capability("test.capability")
        async def my_func(value: int) -> int:
            return value * 2

        # Mock facade to allow
        mock_decision = MagicMock()
        mock_decision.allowed = True
        mock_decision.reason = None
        mock_facade = MagicMock()
        mock_facade.check_principal = AsyncMock(return_value=mock_decision)

        with patch(
            "src.backend.services.authorization.facade.get_authorization_facade",
            return_value=mock_facade,
        ):
            result = await my_func(_principal="user-1", value=21)
            assert result == 42

    @pytest.mark.asyncio
    async def test_denied_capability_raises_connector_auth_error(self) -> None:
        """Если facade deny — ConnectorAuthError raised."""

        @require_capability("test.capability")
        async def my_func() -> str:
            return "should not reach"

        mock_decision = MagicMock()
        mock_decision.allowed = False
        mock_decision.reason = "policy denied: test reason"
        mock_facade = MagicMock()
        mock_facade.check_principal = AsyncMock(return_value=mock_decision)

        with patch(
            "src.backend.services.authorization.facade.get_authorization_facade",
            return_value=mock_facade,
        ):
            with pytest.raises(ConnectorAuthError, match="denied"):
                await my_func(_principal="user-1")

    @pytest.mark.asyncio
    async def test_facade_exception_raises_connector_auth_error(self) -> None:
        """Если facade throws — ConnectorAuthError (НЕ silent пропуск)."""

        @require_capability("test.capability")
        async def my_func() -> str:
            return "should not reach"

        mock_facade = MagicMock()
        mock_facade.check_principal = AsyncMock(
            side_effect=RuntimeError("backend unavailable"),
        )

        with patch(
            "src.backend.services.authorization.facade.get_authorization_facade",
            return_value=mock_facade,
        ):
            with pytest.raises(ConnectorAuthError, match="facade error"):
                await my_func(_principal="user-1")


class TestCheckSourceCapability:
    """check_source_capability — bool return value."""

    @pytest.mark.asyncio
    async def test_allowed_returns_true(self) -> None:
        mock_decision = MagicMock()
        mock_decision.allowed = True
        mock_decision.reason = None
        mock_facade = MagicMock()
        mock_facade.check_principal = AsyncMock(return_value=mock_decision)

        with patch(
            "src.backend.services.authorization.facade.get_authorization_facade",
            return_value=mock_facade,
        ):
            result = await check_source_capability(
                "source.read",
                principal="user-1",
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_denied_returns_false(self) -> None:
        mock_decision = MagicMock()
        mock_decision.allowed = False
        mock_decision.reason = "policy denied"
        mock_facade = MagicMock()
        mock_facade.check_principal = AsyncMock(return_value=mock_decision)

        with patch(
            "src.backend.services.authorization.facade.get_authorization_facade",
            return_value=mock_facade,
        ):
            result = await check_source_capability(
                "source.read",
                principal="user-1",
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_facade_unavailable_returns_false(self) -> None:
        """Fail-closed: facade unavailable → False (НЕ True)."""
        import sys
        original_module = sys.modules.pop(
            "src.backend.services.authorization.facade", None,
        )
        sys.modules["src.backend.services.authorization.facade"] = None
        try:
            result = await check_source_capability(
                "source.read",
                principal="user-1",
            )
            assert result is False
        finally:
            if original_module is not None:
                sys.modules["src.backend.services.authorization.facade"] = original_module
            else:
                sys.modules.pop("src.backend.services.authorization.facade", None)

    @pytest.mark.asyncio
    async def test_facade_exception_returns_false(self) -> None:
        """Fail-closed: facade exception → False (НЕ silent пропуск)."""
        mock_facade = MagicMock()
        mock_facade.check_principal = AsyncMock(
            side_effect=RuntimeError("backend error"),
        )

        with patch(
            "src.backend.services.authorization.facade.get_authorization_facade",
            return_value=mock_facade,
        ):
            result = await check_source_capability(
                "source.read",
                principal="user-1",
            )
            assert result is False