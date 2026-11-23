"""Согласованность слоёв при impersonation (аудит 2026-11-20).

Контракт
--------
Явная capability ``metadata['tenant_impersonation']`` ПЕРЕКЛЮЧАЕТ effective
tenant на target. Инвариант: tenant, который видят все слои, обязан быть
ОДИН И ТОТ ЖЕ:

* ``scope['state']['tenant_id']`` и tenant-контекст (ContextVar → ORM/RLS) —
  ``TenantMiddleware``;
* ``RequestContext.tenant_id`` — ``RequestContextMiddleware`` (его берёт
  DSL-движок первым источником);
* ownership-checker в ``TenantResourceIsolationMiddleware``.

До фикса ``RequestContextMiddleware`` оставался с аутентифицированным
tenant'ом (а state/ContextVar — с target'ом), а resource-isolation отклонял
impersonated-запрос к ресурсу с 403. Capability в production-коде не
выдаётся, поэтому поведение для обычных запросов не меняется.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.auth.auth_context_helpers import resolve_impersonation_target
from src.backend.entrypoints.middlewares.request_context import RequestContextMiddleware
from src.backend.entrypoints.middlewares.tenant_resource_isolation import (
    ResourcePattern,
    TenantResourceIsolationMiddleware,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]

AUTH_TENANT = "tenant-a"
TARGET_TENANT = "tenant-b"


def _auth(metadata: dict[str, Any]) -> AuthContext:
    """Собрать аутентифицированного principal'а.

    Args:
        metadata: ``AuthContext.metadata``.

    Returns:
        Готовый ``AuthContext``.
    """
    return AuthContext(
        method=AuthMethod.JWT, principal="user-of-tenant-a", metadata=metadata
    )


def _scope(
    *, tenant_header: str | None = None, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Собрать ASGI scope с principal'ом и заголовком ``X-Tenant-ID``.

    Args:
        tenant_header: значение заголовка (недоверенный ввод).
        metadata: ``AuthContext.metadata`` (``None`` — без аутентификации).

    Returns:
        Готовый ASGI scope.
    """
    headers: list[tuple[bytes, bytes]] = [(b"host", b"localhost")]
    if tenant_header is not None:
        headers.append((b"x-tenant-id", tenant_header.encode("latin-1")))
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/orders/order-42",
        "headers": headers,
        "state": {},
    }
    if metadata is not None:
        scope["state"]["auth"] = _auth(metadata)
    return scope


async def _receive() -> dict[str, Any]:
    """Пустой receive-канал.

    Returns:
        Сообщение ``http.request`` без тела.
    """
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(message: dict[str, Any]) -> None:
    """Заглушка send-канала (сообщения не проверяются).

    Args:
        message: ASGI-сообщение.
    """
    return None


class TestResolveImpersonationTarget:
    """Общий разбор capability — единый источник истины для всех слоёв."""

    def test_string_capability_allows_exact_target(self) -> None:
        """Строковая capability разрешает ровно указанный tenant.

        Args:
            None.
        """
        auth = _auth({"tenant_id": AUTH_TENANT, "tenant_impersonation": TARGET_TENANT})
        assert resolve_impersonation_target(auth, TARGET_TENANT) == TARGET_TENANT

    def test_whitelist_capability_allows_listed_target(self) -> None:
        """Коллекция capability — whitelist.

        Args:
            None.
        """
        auth = _auth(
            {
                "tenant_id": AUTH_TENANT,
                "tenant_impersonation": [TARGET_TENANT, "tenant-c"],
            }
        )
        assert resolve_impersonation_target(auth, TARGET_TENANT) == TARGET_TENANT

    def test_capability_does_not_allow_other_target(self) -> None:
        """Capability не разрешает tenant, которого в ней нет.

        Args:
            None.
        """
        auth = _auth({"tenant_id": AUTH_TENANT, "tenant_impersonation": "tenant-c"})
        assert resolve_impersonation_target(auth, TARGET_TENANT) is None

    def test_invalid_capability_type_is_rejected(self) -> None:
        """Невалидный тип capability → fail-closed.

        Args:
            None.
        """
        auth = _auth({"tenant_id": AUTH_TENANT, "tenant_impersonation": 42})
        assert resolve_impersonation_target(auth, TARGET_TENANT) is None

    def test_absent_capability_and_absent_auth(self) -> None:
        """Без capability и без principal'а → ``None``.

        Args:
            None.
        """
        auth = _auth({"tenant_id": AUTH_TENANT})
        assert resolve_impersonation_target(auth, TARGET_TENANT) is None
        assert resolve_impersonation_target(None, TARGET_TENANT) is None


class TestRequestContextTenant:
    """``RequestContext.tenant_id`` обязан совпадать с effective tenant."""

    @pytest.mark.asyncio
    async def test_impersonation_switches_request_context_tenant(self) -> None:
        """С capability RequestContext видит target, а не auth-tenant.

        Args:
            None.
        """
        scope = _scope(
            tenant_header=TARGET_TENANT,
            metadata={"tenant_id": AUTH_TENANT, "tenant_impersonation": TARGET_TENANT},
        )
        captured: dict[str, Any] = {}

        async def app(inner_scope, receive, send):
            captured["ctx"] = inner_scope["state"]["request_context"]
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RequestContextMiddleware(app)
        await mw(scope, _receive, _send)

        assert captured["ctx"].tenant_id == TARGET_TENANT

    @pytest.mark.asyncio
    async def test_without_capability_keeps_authenticated_tenant(self) -> None:
        """Без capability поведение прежнее: auth-tenant (fail-closed).

        Args:
            None.
        """
        scope = _scope(tenant_header=TARGET_TENANT, metadata={"tenant_id": AUTH_TENANT})
        captured: dict[str, Any] = {}

        async def app(inner_scope, receive, send):
            captured["ctx"] = inner_scope["state"]["request_context"]
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RequestContextMiddleware(app)
        await mw(scope, _receive, _send)

        assert captured["ctx"].tenant_id == AUTH_TENANT


class TestResourceIsolationTenant:
    """Ownership-checker обязан получать effective tenant."""

    @staticmethod
    def _middleware(app: Any) -> TenantResourceIsolationMiddleware:
        """Собрать middleware с одним checker'ом и одним pattern'ом.

        Args:
            app: downstream-приложение.

        Returns:
            Настроенный middleware.
        """
        pattern = ResourcePattern.compile(
            r"/api/v1/orders/(?P<resource_id>[^/]+)$", "order", "resource_id"
        )
        return TenantResourceIsolationMiddleware(app, patterns=(pattern,))

    @pytest.mark.asyncio
    async def test_impersonation_passes_target_to_ownership_checker(self) -> None:
        """С capability checker получает target (не auth-tenant), 403 нет.

        Args:
            None.
        """
        scope = _scope(
            tenant_header=TARGET_TENANT,
            metadata={"tenant_id": AUTH_TENANT, "tenant_impersonation": TARGET_TENANT},
        )
        seen: dict[str, Any] = {}

        async def checker(resource_id: str, tenant_id: str) -> bool:
            seen["resource_id"] = resource_id
            seen["tenant_id"] = tenant_id
            return True

        async def app(inner_scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = self._middleware(app)
        mw.register_ownership_checker("order", checker)

        messages: list[dict[str, Any]] = []

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        await mw(scope, _receive, send)

        assert seen["tenant_id"] == TARGET_TENANT
        assert seen["resource_id"] == "order-42"
        assert messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_without_capability_mismatch_is_denied(self) -> None:
        """Без capability mismatch остаётся 403 (fail-closed не ослаблен).

        Args:
            None.
        """
        scope = _scope(tenant_header=TARGET_TENANT, metadata={"tenant_id": AUTH_TENANT})

        async def checker(resource_id: str, tenant_id: str) -> bool:
            raise AssertionError("checker не должен вызываться при mismatch")

        async def app(inner_scope, receive, send):
            raise AssertionError("downstream не должен вызываться при deny")

        mw = self._middleware(app)
        mw.register_ownership_checker("order", checker)

        messages: list[dict[str, Any]] = []

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        await mw(scope, _receive, send)

        assert messages[0]["status"] == 403
