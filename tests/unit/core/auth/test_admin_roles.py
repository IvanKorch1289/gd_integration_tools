"""Unit tests for src.backend.core.auth.admin_roles."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.auth.admin_roles import (
    AdminAuthorizationError,
    AdminRole,
    extract_admin_roles,
    require_admin,
)


class TestAdminRole:
    def test_values(self) -> None:
        assert AdminRole.SUPER_ADMIN == "super_admin"
        assert AdminRole.OPERATOR == "operator"
        assert AdminRole.TENANT_ADMIN == "tenant_admin"
        assert AdminRole.READ_ONLY == "read_only"


class TestAdminAuthorizationError:
    def test_attributes(self) -> None:
        exc = AdminAuthorizationError(
            required=(AdminRole.OPERATOR,), actual=frozenset({AdminRole.READ_ONLY})
        )
        assert exc.status_code == 403
        detail = exc.detail
        assert detail["code"] == "admin_role_required"  # type: ignore[index]
        assert detail["required"] == ["operator"]  # type: ignore[index]
        assert detail["actual"] == ["read_only"]  # type: ignore[index]


class TestExtractAdminRoles:
    def test_none(self) -> None:
        assert extract_admin_roles(None) == frozenset()

    def test_empty_metadata(self) -> None:
        ctx = AuthContext(AuthMethod.JWT, "u1")
        assert extract_admin_roles(ctx) == frozenset()

    def test_string(self) -> None:
        ctx = AuthContext(AuthMethod.JWT, "u1", {"admin_roles": "super_admin"})
        assert extract_admin_roles(ctx) == {AdminRole.SUPER_ADMIN}

    def test_list(self) -> None:
        ctx = AuthContext(
            AuthMethod.JWT, "u1", {"admin_roles": ["operator", "read_only"]}
        )
        assert extract_admin_roles(ctx) == {AdminRole.OPERATOR, AdminRole.READ_ONLY}

    def test_invalid_values_skipped(self) -> None:
        ctx = AuthContext(
            AuthMethod.JWT, "u1", {"admin_roles": ["super_admin", "bogus"]}
        )
        assert extract_admin_roles(ctx) == {AdminRole.SUPER_ADMIN}

    def test_non_iterable(self) -> None:
        ctx = AuthContext(AuthMethod.JWT, "u1", {"admin_roles": 123})
        assert extract_admin_roles(ctx) == frozenset()


class TestRequireAdmin:
    @pytest.mark.asyncio
    async def test_has_role(self) -> None:
        dep = require_admin((AdminRole.OPERATOR,))
        request = MagicMock()
        request.state.auth_context = AuthContext(
            AuthMethod.JWT, "u1", {"admin_roles": ["operator"]}
        )
        ctx = await dep(request)
        assert ctx.principal == "u1"

    @pytest.mark.asyncio
    async def test_super_admin_implicit(self) -> None:
        dep = require_admin((AdminRole.OPERATOR,))
        request = MagicMock()
        request.state.auth_context = AuthContext(
            AuthMethod.JWT, "u1", {"admin_roles": ["super_admin"]}
        )
        ctx = await dep(request)
        assert ctx is not None

    @pytest.mark.asyncio
    async def test_missing_context(self) -> None:
        dep = require_admin((AdminRole.OPERATOR,))
        request = MagicMock()
        request.state.auth_context = None
        with pytest.raises(AdminAuthorizationError):
            await dep(request)

    @pytest.mark.asyncio
    async def test_missing_roles(self) -> None:
        dep = require_admin((AdminRole.OPERATOR,))
        request = MagicMock()
        request.state.auth_context = AuthContext(
            AuthMethod.JWT, "u1", {"admin_roles": ["read_only"]}
        )
        with pytest.raises(AdminAuthorizationError):
            await dep(request)
