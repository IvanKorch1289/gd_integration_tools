"""Unit-тесты для AdminRole + require_admin + extract_admin_roles (S13 K1 W2)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.auth.admin_roles import (
    AdminAuthorizationError,
    AdminRole,
    extract_admin_roles,
    require_admin,
)


def _make_ctx(roles: list[str] | str | None) -> AuthContext:
    metadata: dict[str, Any] = {}
    if roles is not None:
        metadata["admin_roles"] = roles
    return AuthContext(method=AuthMethod.JWT, principal="user-1", metadata=metadata)


class TestExtractAdminRoles:
    def test_none_context_returns_empty(self) -> None:
        assert extract_admin_roles(None) == frozenset()

    def test_no_roles_metadata_returns_empty(self) -> None:
        ctx = _make_ctx(None)
        assert extract_admin_roles(ctx) == frozenset()

    def test_single_string_role(self) -> None:
        ctx = _make_ctx("operator")
        assert extract_admin_roles(ctx) == frozenset({AdminRole.OPERATOR})

    def test_list_of_roles(self) -> None:
        ctx = _make_ctx(["operator", "tenant_admin"])
        assert extract_admin_roles(ctx) == frozenset(
            {AdminRole.OPERATOR, AdminRole.TENANT_ADMIN}
        )

    def test_unknown_role_is_skipped(self) -> None:
        ctx = _make_ctx(["operator", "ghost_role"])
        assert extract_admin_roles(ctx) == frozenset({AdminRole.OPERATOR})

    def test_all_unknown_roles_returns_empty(self) -> None:
        ctx = _make_ctx(["ghost_role"])
        assert extract_admin_roles(ctx) == frozenset()


@pytest.fixture
def app_with_admin_endpoint() -> FastAPI:
    app = FastAPI()

    @app.get("/admin/secret", dependencies=[])
    async def _secret(  # type: ignore[no-untyped-def]
        ctx=__import__("fastapi").Depends(
            require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN))
        ),
    ):
        return {"principal": ctx.principal}

    return app


class _InjectAuthMiddleware:
    """Тестовая middleware, ставит auth_context в request.state."""

    def __init__(self, app: Any, ctx: AuthContext | None) -> None:
        self.app = app
        self.ctx = ctx

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})
            scope["state"]["auth_context"] = self.ctx
        await self.app(scope, receive, send)


def _make_app_with_ctx(ctx: AuthContext | None) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject(request, call_next):  # type: ignore[no-untyped-def]
        request.state.auth_context = ctx
        return await call_next(request)

    @app.get("/admin/operator-only")
    async def _operator_only(  # type: ignore[no-untyped-def]
        ctx2=__import__("fastapi").Depends(
            require_admin((AdminRole.OPERATOR,))
        ),
    ):
        return {"ok": True, "principal": ctx2.principal}

    @app.get("/admin/tenant-only")
    async def _tenant_only(  # type: ignore[no-untyped-def]
        ctx2=__import__("fastapi").Depends(
            require_admin((AdminRole.TENANT_ADMIN,))
        ),
    ):
        return {"ok": True}

    return app


class TestRequireAdmin:
    def test_super_admin_passes_for_operator_required(self) -> None:
        ctx = _make_ctx(["super_admin"])
        app = _make_app_with_ctx(ctx)
        client = TestClient(app)
        r = client.get("/admin/operator-only")
        assert r.status_code == 200

    def test_operator_passes(self) -> None:
        ctx = _make_ctx(["operator"])
        app = _make_app_with_ctx(ctx)
        client = TestClient(app)
        r = client.get("/admin/operator-only")
        assert r.status_code == 200

    def test_tenant_admin_blocked_for_operator(self) -> None:
        ctx = _make_ctx(["tenant_admin"])
        app = _make_app_with_ctx(ctx)
        client = TestClient(app)
        r = client.get("/admin/operator-only")
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "admin_role_required"

    def test_no_context_returns_403(self) -> None:
        app = _make_app_with_ctx(None)
        client = TestClient(app)
        r = client.get("/admin/operator-only")
        assert r.status_code == 403

    def test_empty_roles_returns_403(self) -> None:
        ctx = _make_ctx([])
        app = _make_app_with_ctx(ctx)
        client = TestClient(app)
        r = client.get("/admin/operator-only")
        assert r.status_code == 403

    def test_super_admin_passes_for_tenant(self) -> None:
        ctx = _make_ctx(["super_admin"])
        app = _make_app_with_ctx(ctx)
        client = TestClient(app)
        r = client.get("/admin/tenant-only")
        assert r.status_code == 200
