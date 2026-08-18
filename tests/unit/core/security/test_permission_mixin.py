"""Coverage tests для permission_mixin (Sprint 222, 2026-08-17).

TDD: tests для core/security/authorization_gateway/permission_mixin.py.

permission_mixin.py coverage baseline: 17% (per Sprint 221 analysis).
Target: 90%+ via these tests.

Coverage targets:
- permission_step: no required permissions → allow
- feature flag OFF → no-op allow
- feature flag unavailable → deny (fail-closed)
- no permissions in context → deny
- all required permissions present → allow
- some required permissions missing → deny with detail
- PermissionMixin is a static factory
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.security.authorization_gateway.permission_mixin import (
    PermissionMixin,
)
from src.backend.core.security.authorization_gateway.state import (
    AuthorizationReason,
    PolicyDecider,
)


class TestPermissionMixinFactory:
    """permission_step — factory для PolicyDecider."""

    def test_returns_callable_policy_decider(self) -> None:
        result = PermissionMixin.permission_step(("role:admin",))
        assert callable(result)
        assert result.__name__ == "permission_step"

    def test_with_empty_required_permissions_still_returns_decider(self) -> None:
        """Empty required_permissions — factory всё равно возвращает decider."""
        result = PermissionMixin.permission_step(())
        assert callable(result)


class TestPermissionStepNoRequired:
    """Empty required_permissions → allow (no-op)."""

    @pytest.mark.asyncio
    async def test_no_required_permissions_returns_allow(self) -> None:
        decider = PermissionMixin.permission_step(())
        result = await decider(
            principal="user-1",
            resource="test",
            action="read",
            ctx={"permissions": ()},
        )
        assert isinstance(result, AuthorizationReason)
        assert result.outcome == "allow"
        assert result.detail == "no_required_permissions"
        assert result.source == "permission"


class TestPermissionStepFeatureFlag:
    """Feature flag OFF → no-op allow."""

    @pytest.mark.asyncio
    async def test_feature_flag_off_returns_allow(self) -> None:
        decider = PermissionMixin.permission_step(("role:admin",))

        # Mock feature flag service to return disabled
        mock_service = MagicMock()
        mock_service.is_enabled.return_value = False

        with patch(
            "src.backend.core.feature_flags.get_feature_flag_service",
            return_value=mock_service,
        ):
            result = await decider(
                principal="user-1",
                resource="test",
                action="read",
                ctx={"permissions": ("role:admin",)},
            )

        assert result.outcome == "allow"
        assert result.detail == "route_authz_requires_permission=False"

    @pytest.mark.asyncio
    async def test_feature_flag_unavailable_returns_deny(self) -> None:
        """Fail-closed: feature flag service unavailable → deny."""
        decider = PermissionMixin.permission_step(("role:admin",))

        # Patch to raise exception during feature flag lookup
        with patch(
            "src.backend.core.feature_flags.get_feature_flag_service",
            side_effect=RuntimeError("flag service down"),
        ):
            result = await decider(
                principal="user-1",
                resource="test",
                action="read",
                ctx={"permissions": ("role:admin",)},
            )

        assert result.outcome == "deny"
        assert result.detail == "feature_flag_unavailable"


class TestPermissionStepContext:
    """No permissions in context → deny."""

    @pytest.mark.asyncio
    async def test_no_permissions_in_context_returns_deny(self) -> None:
        decider = PermissionMixin.permission_step(("role:admin",))

        # Mock feature flag ON, but ctx has no permissions
        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True

        with patch(
            "src.backend.core.feature_flags.get_feature_flag_service",
            return_value=mock_service,
        ):
            result = await decider(
                principal="user-1",
                resource="test",
                action="read",
                ctx={},  # no permissions key
            )

        assert result.outcome == "deny"
        assert result.detail == "no_permissions_in_context"

    @pytest.mark.asyncio
    async def test_empty_permissions_tuple_returns_deny(self) -> None:
        """ctx['permissions'] существует, но пустой кортеж → deny."""
        decider = PermissionMixin.permission_step(("role:admin",))

        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True

        with patch(
            "src.backend.core.feature_flags.get_feature_flag_service",
            return_value=mock_service,
        ):
            result = await decider(
                principal="user-1",
                resource="test",
                action="read",
                ctx={"permissions": ()},
            )

        assert result.outcome == "deny"
        assert result.detail == "no_permissions_in_context"


class TestPermissionStepAllowed:
    """All required permissions present → allow."""

    @pytest.mark.asyncio
    async def test_all_required_permissions_present_returns_allow(self) -> None:
        decider = PermissionMixin.permission_step(
            ("role:admin", "scope:credit.read"),
        )

        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True

        with patch(
            "src.backend.core.feature_flags.get_feature_flag_service",
            return_value=mock_service,
        ):
            result = await decider(
                principal="user-1",
                resource="credit",
                action="read",
                ctx={"permissions": ("role:admin", "scope:credit.read", "extra")},
            )

        assert result.outcome == "allow"
        assert result.detail is None
        assert result.source == "permission"


class TestPermissionStepDenied:
    """Missing permissions → deny with detail."""

    @pytest.mark.asyncio
    async def test_missing_some_permissions_returns_deny(self) -> None:
        """Some required permissions are missing → deny with detail."""
        decider = PermissionMixin.permission_step(
            ("role:admin", "scope:credit.read"),
        )

        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True

        with patch(
            "src.backend.core.feature_flags.get_feature_flag_service",
            return_value=mock_service,
        ):
            result = await decider(
                principal="user-1",
                resource="credit",
                action="read",
                ctx={"permissions": ("role:admin",)},  # missing scope:credit.read
            )

        assert result.outcome == "deny"
        assert "missing_permissions" in result.detail
        assert "scope:credit.read" in result.detail

    @pytest.mark.asyncio
    async def test_all_permissions_missing_returns_deny(self) -> None:
        decider = PermissionMixin.permission_step(
            ("role:admin", "scope:credit.read"),
        )

        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True

        with patch(
            "src.backend.core.feature_flags.get_feature_flag_service",
            return_value=mock_service,
        ):
            result = await decider(
                principal="user-1",
                resource="credit",
                action="read",
                ctx={"permissions": ("role:other",)},
            )

        assert result.outcome == "deny"
        assert "role:admin" in result.detail
        assert "scope:credit.read" in result.detail


class TestPermissionStepIntegration:
    """Integration scenarios with multiple required permissions."""

    @pytest.mark.asyncio
    async def test_single_role_required_and_present(self) -> None:
        """Single role required, present in context → allow."""
        decider = PermissionMixin.permission_step(("role:admin",))

        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True

        with patch(
            "src.backend.core.feature_flags.get_feature_flag_service",
            return_value=mock_service,
        ):
            result = await decider(
                principal="admin-user",
                resource="users",
                action="delete",
                ctx={"permissions": ("role:admin",)},
            )

        assert result.outcome == "allow"

    @pytest.mark.asyncio
    async def test_mixed_prefixes(self) -> None:
        """Mixed role: и scope: prefixes — все required present → allow."""
        decider = PermissionMixin.permission_step(
            ("role:user", "scope:read.public", "scope:read.private"),
        )

        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True

        with patch(
            "src.backend.core.feature_flags.get_feature_flag_service",
            return_value=mock_service,
        ):
            result = await decider(
                principal="user-1",
                resource="documents",
                action="read",
                ctx={
                    "permissions": (
                        "role:user",
                        "scope:read.public",
                        "scope:read.private",
                        "scope:write",
                    ),
                },
            )

        assert result.outcome == "allow"