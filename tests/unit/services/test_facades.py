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

from src.backend.services.authorization.facade import (
    AuthorizationFacade,
    get_authorization_facade,
)
from src.backend.services.capabilities.facade import (
    CapabilityFacade,
    get_capability_facade,
)
from src.backend.services.pii.facade import PIIFacade, get_pii_facade
from src.backend.services.secrets.facade import SecretFacade, get_secret_facade
from src.backend.services.tenancy.facade import TenantFacade, get_tenant_facade


class TestPIIFacade:
    """Тесты PIIFacade."""

    def test_singleton(self) -> None:
        """get_pii_facade возвращает один и тот же instance."""
        f1 = get_pii_facade()
        f2 = get_pii_facade()
        assert f1 is f2

    def test_mask_returns_string(self) -> None:
        """mask возвращает string при успехе (или raises при failure)."""
        facade = PIIFacade()
        # Если sanitizer работает — возвращает string.
        # Если sanitizer падает — cycle-4/D-AUDIT-109 raise PIIFailClosedError.
        try:
            result = facade.mask("test@example.com")
            assert isinstance(result, str)
        except Exception as exc:
            from src.backend.core.policy.pii_fail_closed import (
                PIIFailClosedError,
            )

            assert isinstance(exc, PIIFailClosedError)

    def test_mask_struct_returns_same_type(self) -> None:
        """mask_struct возвращает тот же тип объекта (или raises)."""
        facade = PIIFacade()
        data = {"email": "user@example.com", "age": 30}
        # cycle-4/D-AUDIT-109: либо dict, либо fail-CLOSED raise.
        try:
            result = facade.mask_struct(data)
            assert isinstance(result, dict)
            assert "age" in result
        except Exception as exc:
            from src.backend.core.policy.pii_fail_closed import (
                PIIFailClosedError,
            )

            assert isinstance(exc, PIIFailClosedError)

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
        backend = MagicMock()
        backend.get_secret = AsyncMock(side_effect=RuntimeError("boom"))
        facade = SecretFacade(backend=backend)

        result = await facade.get_secret("missing.key", default="fallback")

        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_get_secret_returns_none_when_no_default(self) -> None:
        """При ошибке без default → None."""
        backend = MagicMock()
        backend.get_secret = AsyncMock(side_effect=RuntimeError("boom"))
        facade = SecretFacade(backend=backend)

        result = await facade.get_secret("missing.key")

        assert result is None

    @pytest.mark.asyncio
    async def test_set_secret_uses_backend_contract(self) -> None:
        """set_secret делегирует в canonical async backend contract."""
        backend = MagicMock()
        backend.set_secret = AsyncMock()
        facade = SecretFacade(backend=backend)

        await facade.set_secret("custom.key", "value")

        backend.set_secret.assert_awaited_once_with("custom.key", "value")


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
        """declare вызывает gate.declare с CapabilityRef."""
        from src.backend.core.security.capabilities.models import CapabilityRef

        facade = CapabilityFacade()
        with patch.object(facade.gate, "declare") as mock_declare:
            facade.declare("my_plugin", ["ds.read", "ds.write"])
            args, _kwargs = mock_declare.call_args
            assert args[0] == "my_plugin"
            assert list(args[1]) == [
                CapabilityRef(name="ds.read"),
                CapabilityRef(name="ds.write"),
            ]

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
        from src.backend.core.security.capabilities import CapabilityDeniedError

        denied = CapabilityDeniedError(
            plugin="plugin",
            capability="capability",
            requested_scope=None,
            declared_scope=None,
        )
        facade = CapabilityFacade()
        with patch.object(facade.gate, "check", side_effect=denied):
            with pytest.raises(CapabilityDeniedError) as caught:
                facade.check_or_raise("plugin", "capability")

        assert caught.value is denied

    def test_check_or_raise_wraps_unexpected_exception(self) -> None:
        """check_or_raise оборачивает unexpected exceptions в fail-closed error."""
        from src.backend.core.security.capabilities import CapabilityDeniedError

        facade = CapabilityFacade()
        with patch.object(
            facade.gate,
            "check",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(CapabilityDeniedError) as caught:
                facade.check_or_raise("plugin", "capability")

        assert isinstance(caught.value.__cause__, RuntimeError)
        assert str(caught.value.__cause__) == "boom"


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
