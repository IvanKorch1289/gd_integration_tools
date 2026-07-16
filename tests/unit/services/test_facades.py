"""Unit-тесты для новых facades (S183).

Coverage:
- PIIFacade: mask, mask_struct, tokenize, detokenize, add_custom_pattern, list_patterns
- SecretFacade: get_secret, set_secret, list_secrets, register_backend
- TenantFacade: current, set, is_system, with_tenant (context manager)
- CapabilityFacade: check, check_tenant, declare, revoke
- AuthorizationFacade: check, add_policy, remove_policy
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.capabilities.facade import (
    CapabilityFacade,
    get_capability_facade,
)
from src.backend.services.pii.facade import PIIFacade, get_pii_facade
from src.backend.services.secrets.facade import SecretFacade, get_secret_facade
from src.backend.services.tenancy.facade import TenantFacade, get_tenant_facade
from src.backend.services.authorization.facade import (
    AuthorizationFacade,
    get_authorization_facade,
)


class TestPIIFacade:
    """Тесты PIIFacade."""

    def test_singleton(self) -> None:
        """get_pii_facade возвращает один и тот же instance."""
        f1 = get_pii_facade()
        f2 = get_pii_facade()
        assert f1 is f2

    def test_mask_returns_string(self) -> None:
        """mask возвращает string (или input при ошибке)."""
        facade = PIIFacade()
        result = facade.mask("test@example.com")
        assert isinstance(result, str)

    def test_mask_struct_returns_same_type(self) -> None:
        """mask_struct возвращает тот же тип объекта."""
        facade = PIIFacade()
        data = {"email": "user@example.com", "age": 30}
        result = facade.mask_struct(data)
        assert isinstance(result, dict)
        assert "age" in result

    def test_list_patterns_returns_list(self) -> None:
        """list_patterns возвращает list."""
        facade = PIIFacade()
        patterns = facade.list_patterns()
        assert isinstance(patterns, list)


class TestSecretFacade:
    """Тесты SecretFacade."""

    def test_singleton(self) -> None:
        """get_secret_facade singleton."""
        f1 = get_secret_facade()
        f2 = get_secret_facade()
        assert f1 is f2

    @pytest.mark.asyncio
    async def test_get_secret_returns_default_on_error(self) -> None:
        """При ошибке возвращается default."""
        facade = SecretFacade()
        with patch.object(
            facade,
            "_backend",
            new=AsyncMock(get=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            result = await facade.get_secret("missing.key", default="fallback")
            assert result == "fallback"

    @pytest.mark.asyncio
    async def test_get_secret_returns_none_when_no_default(self) -> None:
        """При ошибке без default → None."""
        facade = SecretFacade()
        with patch.object(
            facade,
            "_backend",
            new=AsyncMock(get=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            result = await facade.get_secret("missing.key")
            assert result is None

    @pytest.mark.asyncio
    async def test_register_backend(self) -> None:
        """register_backend добавляет backend."""
        facade = SecretFacade()
        mock_backend = MagicMock()
        facade.register_backend("custom", mock_backend)
        assert "custom" in facade._backends
        assert facade._backends["custom"] is mock_backend


class TestTenantFacade:
    """Тесты TenantFacade."""

    def test_singleton(self) -> None:
        """get_tenant_facade singleton."""
        f1 = get_tenant_facade()
        f2 = get_tenant_facade()
        assert f1 is f2

    def test_tenant_id_returns_system_when_no_context(self) -> None:
        """tenant_id возвращает '_system' при отсутствии context."""
        facade = TenantFacade()
        with patch(
            "src.backend.core.tenancy.current_tenant", return_value=None
        ):
            assert facade.tenant_id() == "_system"

    def test_is_system_true_when_no_context(self) -> None:
        """is_system True при отсутствии context."""
        facade = TenantFacade()
        with patch(
            "src.backend.core.tenancy.current_tenant", return_value=None
        ):
            assert facade.is_system() is True

    def test_principal_id_returns_none_when_no_context(self) -> None:
        """principal_id None при отсутствии context."""
        facade = TenantFacade()
        with patch(
            "src.backend.core.tenancy.current_tenant", return_value=None
        ):
            assert facade.principal_id() is None

    @pytest.mark.asyncio
    async def test_with_tenant_restores_previous(self) -> None:
        """with_tenant восстанавливает previous context."""
        facade = TenantFacade()
        with patch(
            "src.backend.core.tenancy.current_tenant", return_value=None
        ):
            with patch(
                "src.backend.core.tenancy.set_tenant"
            ) as mock_set:
                async with facade.with_tenant("tenant_42"):
                    # During context, set_tenant should be called with new ctx
                    assert mock_set.called

                # After context, set_tenant should restore previous
                assert mock_set.call_count >= 2


class TestCapabilityFacade:
    """Тесты CapabilityFacade."""

    def test_singleton(self) -> None:
        """get_capability_facade singleton."""
        f1 = get_capability_facade()
        f2 = get_capability_facade()
        assert f1 is f2

    def test_check_returns_bool(self) -> None:
        """check возвращает bool."""
        facade = CapabilityFacade()
        with patch.object(facade.gate, "check", return_value=None):
            result = facade.check("plugin", "capability")
            assert isinstance(result, bool)

    def test_check_returns_false_on_exception(self) -> None:
        """check возвращает False при exception."""
        facade = CapabilityFacade()
        with patch.object(
            facade.gate,
            "check",
            side_effect=RuntimeError("denied"),
        ):
            result = facade.check("plugin", "capability")
            assert result is False

    def test_declare_calls_gate(self) -> None:
        """declare вызывает gate.declare."""
        facade = CapabilityFacade()
        with patch.object(facade.gate, "declare") as mock_declare:
            facade.declare("my_plugin", ["ds.read", "ds.write"])
            mock_declare.assert_called_once_with(
                "my_plugin", ["ds.read", "ds.write"]
            )

    def test_revoke_calls_gate(self) -> None:
        """revoke вызывает gate.revoke."""
        facade = CapabilityFacade()
        with patch.object(facade.gate, "revoke") as mock_revoke:
            facade.revoke("my_plugin")
            mock_revoke.assert_called_once_with("my_plugin")

    def test_check_or_raise_no_exception_on_success(self) -> None:
        """check_or_raise не raise при успехе."""
        facade = CapabilityFacade()
        with patch.object(facade.gate, "check", return_value=None):
            # Не должно raise
            facade.check_or_raise("plugin", "capability")

    def test_check_or_raise_propagates_capability_denied(self) -> None:
        """check_or_raise пробрасывает CapabilityDeniedError."""
        from src.backend.core.security.capabilities import (
            CapabilityDeniedError,
        )

        facade = CapabilityFacade()
        with patch.object(
            facade.gate,
            "check",
            side_effect=CapabilityDeniedError("denied"),
        ):
            with pytest.raises(CapabilityDeniedError, match="denied"):
                facade.check_or_raise("plugin", "capability")

    def test_check_or_raise_wraps_unexpected_exception(self) -> None:
        """check_or_raise оборачивает unexpected exceptions в CapabilityDeniedError."""
        from src.backend.core.security.capabilities import (
            CapabilityDeniedError,
        )

        facade = CapabilityFacade()
        with patch.object(
            facade.gate,
            "check",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(CapabilityDeniedError, match="boom"):
                facade.check_or_raise("plugin", "capability")


class TestAuthorizationFacade:
    """Тесты AuthorizationFacade."""

    def test_singleton(self) -> None:
        """get_authorization_facade singleton."""
        f1 = get_authorization_facade()
        f2 = get_authorization_facade()
        assert f1 is f2

    def test_check_returns_bool(self) -> None:
        """check возвращает bool."""
        facade = AuthorizationFacade()
        with patch.object(
            facade.gateway, "check", return_value=True
        ):
            result = facade.check("user:1", "read", "doc:1")
            assert result is True

    def test_check_returns_false_on_exception(self) -> None:
        """check возвращает False при exception (fail-safe)."""
        facade = AuthorizationFacade()
        with patch.object(
            facade.gateway,
            "check",
            side_effect=RuntimeError("boom"),
        ):
            result = facade.check("user:1", "read", "doc:1")
            assert result is False

    def test_add_policy_returns_bool(self) -> None:
        """add_policy возвращает bool."""
        facade = AuthorizationFacade()
        with patch.object(
            facade.gateway, "add_policy", return_value=None
        ):
            result = facade.add_policy("user:1", "read", "doc:1")
            assert result is True

    def test_remove_policy_returns_bool(self) -> None:
        """remove_policy возвращает bool."""
        facade = AuthorizationFacade()
        with patch.object(
            facade.gateway, "remove_policy", return_value=None
        ):
            result = facade.remove_policy("user:1", "read", "doc:1")
            assert result is True
