"""ADR-0421 — проверка прав на auto-/invocation-поверхности.

До ADR-0421:

* ``POST /api/v1/auto/admin.get_config`` отдавал ``settings.model_dump()``
  любому аутентифицированному пользователю;
* ``POST /api/v1/invocations`` был универсальным диспетчером без
  авторизации — произвольный action достижим любому аутентифицированному.

Тесты проверяют fail-closed поведение (403 без правы) и успешный путь
с корректной admin-ролью.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.config.settings import settings
from src.backend.core.interfaces.invoker import (
    InvocationMode,
    InvocationResponse,
    InvocationStatus,
)
from src.backend.dsl.commands.action_registry import (
    ADMIN_PERMISSION,
    ActionHandlerRegistry,
)
from src.backend.entrypoints.api.generator.auto_register import (
    _AUTO_PREFIX,
    auto_register_unrouted_actions,
)
from src.backend.entrypoints.api.v1.endpoints.invocations import (
    router as invocations_router,
)

# ──────────────────────────────────────────────────────────────────────
#  Общие хелперы
# ──────────────────────────────────────────────────────────────────────


class _AdminLikeService:
    """Сервис-имитация ``AdminService`` (отдаёт конфигурацию приложения)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def get_config(self) -> dict[str, Any]:
        self.calls.append({})
        return settings.model_dump()


def _auth(
    *,
    principal: str = "user-1",
    admin_roles: list[str] | None = None,
    permissions: list[str] | None = None,
) -> AuthContext:
    """Строит ``AuthContext`` для подстановки в ``request.state.auth``."""
    metadata: dict[str, Any] = {}
    if admin_roles is not None:
        metadata["admin_roles"] = admin_roles
    if permissions is not None:
        metadata["permissions"] = permissions
    return AuthContext(method=AuthMethod.JWT, principal=principal, metadata=metadata)


def _app_with_auth(auth: AuthContext | None) -> FastAPI:
    """FastAPI-app, middleware которого кладёт ``request.state.auth``."""
    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request: Request, call_next: Any) -> Any:
        request.state.auth = auth
        return await call_next(request)

    return app


@pytest.fixture(autouse=True)
def _no_audit_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отключает реальный ClickHouse-audit в тестах (нет сетевых вызовов)."""
    audit_service = AsyncMock()
    monkeypatch.setattr(
        "src.backend.core.audit.facade.audit_service.get_unified_audit_service",
        lambda: audit_service,
    )


# ──────────────────────────────────────────────────────────────────────
#  Auto-поверхность (/api/v1/auto/<action>)
# ──────────────────────────────────────────────────────────────────────


class TestAutoSurfacePermissions:
    """``POST /api/v1/auto/<action>`` — требует прав для admin-action'ов."""

    def _build(self, auth: AuthContext | None) -> tuple[TestClient, _AdminLikeService]:
        registry = ActionHandlerRegistry()
        service = _AdminLikeService()
        registry.register(
            action="admin.get_config",
            service_getter=lambda: service,
            service_method="get_config",
        )
        app = _app_with_auth(auth)
        auto_register_unrouted_actions(app, registry)
        return TestClient(app), service

    def test_admin_action_denied_without_rights(self) -> None:
        client, service = self._build(_auth(principal="user-1"))

        response = client.post(f"{_AUTO_PREFIX}/admin.get_config", json={})

        assert response.status_code == 403
        body = response.json()
        assert body["detail"]["code"] == "action_permission_denied"
        assert body["detail"]["action"] == "admin.get_config"
        # Настройки приложения НЕ отданы.
        assert service.calls == []
        assert "database" not in response.text

    def test_admin_action_allowed_with_admin_role(self) -> None:
        client, service = self._build(
            _auth(principal="admin:alice", admin_roles=["super_admin"])
        )

        response = client.post(f"{_AUTO_PREFIX}/admin.get_config", json={})

        assert response.status_code == 200
        assert service.calls == [{}]
        assert "app" in response.json()

    def test_admin_action_allowed_with_explicit_permission(self) -> None:
        client, service = self._build(
            _auth(principal="svc", permissions=[ADMIN_PERMISSION])
        )

        response = client.post(f"{_AUTO_PREFIX}/admin.get_config", json={})

        assert response.status_code == 200
        assert service.calls == [{}]

    def test_anonymous_admin_action_denied(self) -> None:
        """Без auth-контекста admin-action недоступен (fail-closed)."""
        client, service = self._build(None)

        response = client.post(f"{_AUTO_PREFIX}/admin.get_config", json={})

        assert response.status_code == 403
        assert service.calls == []

    def test_non_admin_action_still_reachable(self) -> None:
        """Backward compat: обычные action'ы не требуют прав."""
        registry = ActionHandlerRegistry()

        class _Echo:
            async def run(self, **kwargs: Any) -> dict[str, Any]:
                return {"ok": True}

        registry.register(
            action="demo.run", service_getter=lambda: _Echo(), service_method="run"
        )
        app = _app_with_auth(None)
        auto_register_unrouted_actions(app, registry)
        client = TestClient(app)

        response = client.post(f"{_AUTO_PREFIX}/demo.run", json={})

        assert response.status_code == 200
        assert response.json() == {"ok": True}


# ──────────────────────────────────────────────────────────────────────
#  Invocation-поверхность (/api/v1/invocations)
# ──────────────────────────────────────────────────────────────────────


class TestInvocationSurfacePermissions:
    """``POST /api/v1/invocations`` — универсальный диспетчер с проверкой прав."""

    def _build(self, auth: AuthContext | None) -> tuple[TestClient, MagicMock]:
        app = _app_with_auth(auth)
        app.include_router(invocations_router, prefix="/invocations")
        invoker = MagicMock()
        invoker.invoke = AsyncMock(
            return_value=InvocationResponse(
                invocation_id="inv-1",
                status=InvocationStatus.OK,
                result={"ok": True},
                mode=InvocationMode.SYNC,
            )
        )
        app.state.invoker = invoker
        return TestClient(app), invoker

    def test_admin_action_denied_without_rights(self) -> None:
        client, invoker = self._build(_auth(principal="user-1"))

        response = client.post(
            "/invocations", json={"action": "admin.get_config", "mode": "sync"}
        )

        assert response.status_code == 403
        body = response.json()
        assert body["detail"]["code"] == "action_permission_denied"
        # Invoker не вызывался — действие не запускалось.
        invoker.invoke.assert_not_awaited()

    def test_admin_action_allowed_with_admin_role(self) -> None:
        client, invoker = self._build(
            _auth(principal="admin:alice", admin_roles=["super_admin"])
        )

        response = client.post(
            "/invocations", json={"action": "admin.get_config", "mode": "sync"}
        )

        assert response.status_code == 200
        invoker.invoke.assert_awaited_once()
        request = invoker.invoke.call_args[0][0]
        assert ADMIN_PERMISSION in request.permissions
        assert request.principal == "admin:alice"

    def test_anonymous_admin_action_denied(self) -> None:
        client, invoker = self._build(None)

        response = client.post(
            "/invocations", json={"action": "admin.get_config", "mode": "sync"}
        )

        assert response.status_code == 403
        invoker.invoke.assert_not_awaited()

    def test_non_admin_action_allowed(self) -> None:
        client, invoker = self._build(_auth(principal="user-1"))

        response = client.post(
            "/invocations", json={"action": "orders.get", "mode": "sync"}
        )

        assert response.status_code == 200
        invoker.invoke.assert_awaited_once()
