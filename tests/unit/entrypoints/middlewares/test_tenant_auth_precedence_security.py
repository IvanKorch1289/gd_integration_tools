"""Регрессия SECURITY-P0-002: заголовок X-Tenant-ID не переопределяет
аутентифицированный tenant (fail-closed 403 tenant_mismatch).

Контекст дефекта
----------------
До фикса приоритет tenant_id в :class:`TenantMiddleware` был
``header > state > default``, а аутентифицированный tenant из
``AuthContext.metadata['tenant_id']`` вообще не учитывался. Runtime-
воспроизведение (артефакт ``artifacts/current_audit/tenant_spoofing.json``):

* ``auth tenant-a`` + ``X-Tenant-ID: tenant-b`` → **HTTP 200**,
  ``state['tenant_id'] == 'tenant-b'`` (ожидалось 403 tenant_mismatch);
* ``auth tenant-a`` без заголовка → ``state['tenant_id'] == 'default'``
  (аутентифицированный tenant терялся).

Контракт после фикса
--------------------
1. Аутентифицированный tenant авторитетен.
2. Расхождение с заголовком → 403 ``tenant_mismatch`` (fail-closed).
3. Явная impersonation capability (``metadata['tenant_impersonation']``)
   разрешает подмену ровно на перечисленный tenant.
4. Без аутентификации поведение не меняется (header > state > default).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

pytestmark = pytest.mark.asyncio

AUTH_TENANT = "tenant-a"
HEADER_TENANT = "tenant-b"
RESOURCE_PATH = "/api/v1/orders/order-42"


def _make_inner(observed: dict[str, Any]):
    """Downstream-наблюдатель: фиксирует state и отвечает 200."""

    async def inner(scope, receive, send):  # type: ignore[no-untyped-def]
        state = scope.get("state", {}) or {}
        auth = state.get("auth")
        observed["state_tenant_id"] = state.get("tenant_id")
        observed["auth_tenant_id"] = (
            auth.metadata.get("tenant_id") if auth is not None else None
        )
        body = json.dumps({"tenant": state.get("tenant_id")}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return inner


def _scope(
    *, tenant_header: str | None = None, auth_metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Собрать ASGI scope как его выдаёт uvicorn."""
    headers: list[tuple[bytes, bytes]] = [(b"host", b"localhost")]
    if tenant_header is not None:
        headers.append((b"x-tenant-id", tenant_header.encode()))
    state: dict[str, Any] = {}
    if auth_metadata is not None:
        # Контракт upstream: AuthRequiredMiddleware кладёт AuthContext в
        # scope['state']['auth'] (auth_required.py:184).
        state["auth"] = AuthContext(
            method=AuthMethod.JWT, principal="user-of-tenant-a", metadata=auth_metadata
        )
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": RESOURCE_PATH,
        "raw_path": RESOURCE_PATH.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 55555),
        "server": ("localhost", 8000),
        "state": state,
    }


async def _call(app: Any, scope: dict[str, Any]) -> tuple[int, dict[bytes, str], bytes]:
    """Выполнить запрос и вернуть (status, headers, body)."""
    captured: dict[str, Any] = {"status": None, "headers": {}, "body": b""}

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message.get("type") == "http.response.start":
            captured["status"] = message.get("status")
            for k, v in message.get("headers", []):
                captured["headers"][k] = v.decode("latin-1")
        elif message.get("type") == "http.response.body":
            captured["body"] = message.get("body", b"")

    await app(scope, receive, send)
    return captured["status"], captured["headers"], captured["body"]


async def test_spoofed_tenant_header_is_rejected_403() -> None:
    """Ядро P0: header tenant-b при аутентификации в tenant-a → 403."""
    observed: dict[str, Any] = {}
    app = TenantMiddleware(_make_inner(observed))

    status, _, body = await _call(
        app,
        _scope(tenant_header=HEADER_TENANT, auth_metadata={"tenant_id": AUTH_TENANT}),
    )

    assert status == 403
    assert json.loads(body)["error"] == "tenant_mismatch"
    # Handler НЕ вызван — данные tenant-b не могли быть прочитаны.
    assert observed == {}


async def test_matching_tenant_header_is_allowed() -> None:
    """Совпадающий заголовок не конфликтует с аутентифицированным tenant."""
    observed: dict[str, Any] = {}
    app = TenantMiddleware(_make_inner(observed))

    status, headers, _ = await _call(
        app, _scope(tenant_header=AUTH_TENANT, auth_metadata={"tenant_id": AUTH_TENANT})
    )

    assert status == 200
    assert observed["state_tenant_id"] == AUTH_TENANT
    assert headers[b"x-tenant-id"] == AUTH_TENANT


async def test_authenticated_tenant_is_used_without_header() -> None:
    """Без заголовка используется аутентифицированный tenant, не 'default'."""
    observed: dict[str, Any] = {}
    app = TenantMiddleware(_make_inner(observed), default_tenant="default")

    status, headers, _ = await _call(
        app, _scope(auth_metadata={"tenant_id": AUTH_TENANT})
    )

    assert status == 200
    assert observed["state_tenant_id"] == AUTH_TENANT
    assert headers[b"x-tenant-id"] == AUTH_TENANT


async def test_explicit_impersonation_capability_allows_target() -> None:
    """Явная capability разрешает подмену ровно на разрешённый tenant."""
    observed: dict[str, Any] = {}
    app = TenantMiddleware(_make_inner(observed))

    status, _, _ = await _call(
        app,
        _scope(
            tenant_header=HEADER_TENANT,
            auth_metadata={
                "tenant_id": AUTH_TENANT,
                "tenant_impersonation": HEADER_TENANT,
            },
        ),
    )

    assert status == 200
    # Impersonation НЕ меняет идентичность запроса: tenant остаётся tenant-a.
    assert observed["state_tenant_id"] == AUTH_TENANT


async def test_impersonation_capability_does_not_leak_to_other_tenants() -> None:
    """Capability на tenant-b не разрешает подмену на любой другой tenant."""
    observed: dict[str, Any] = {}
    app = TenantMiddleware(_make_inner(observed))

    status, _, _ = await _call(
        app,
        _scope(
            tenant_header="tenant-c",
            auth_metadata={
                "tenant_id": AUTH_TENANT,
                "tenant_impersonation": [HEADER_TENANT],
            },
        ),
    )

    assert status == 403
    assert observed == {}


async def test_header_trusted_when_no_authentication() -> None:
    """Без аутентификации контракт не меняется: header > state > default."""
    observed: dict[str, Any] = {}
    app = TenantMiddleware(_make_inner(observed), default_tenant="default")

    status, headers, _ = await _call(app, _scope(tenant_header=HEADER_TENANT))

    assert status == 200
    assert observed["state_tenant_id"] == HEADER_TENANT
    assert headers[b"x-tenant-id"] == HEADER_TENANT


# --- RequestContextMiddleware: второй источник подмены ------------------
# RequestContextMiddleware зарегистрирован с order=320 и из-за LIFO
# выполняется РАНЬШЕ TenantMiddleware (order=300), поэтому state['tenant_id']
# там ещё недоступен. DSL-движок берёт tenant из RequestContext ПЕРВЫМ
# источником (dsl/engine/execution_engine.py:26-40) — без фикса здесь
# подделанный tenant доходил бы до пайплайна DSL.


async def test_request_context_uses_authenticated_tenant_over_header() -> None:
    """RequestContext получает аутентифицированный tenant, не подделанный."""
    from src.backend.entrypoints.middlewares.request_context import (
        RequestContextMiddleware,
    )

    captured: dict[str, Any] = {}

    async def inner(scope, receive, send):  # type: ignore[no-untyped-def]
        captured["request_context"] = scope.get("state", {}).get("request_context")
        body = b"{}"
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})

    app = RequestContextMiddleware(inner)
    await _call(
        app,
        _scope(tenant_header=HEADER_TENANT, auth_metadata={"tenant_id": AUTH_TENANT}),
    )

    ctx = captured["request_context"]
    assert ctx is not None
    assert ctx.tenant_id == AUTH_TENANT, (
        f"RequestContext принял подделанный tenant: {ctx.tenant_id!r}"
    )


async def test_request_context_header_only_when_unauthenticated() -> None:
    """Без аутентификации RequestContext по-прежнему берёт tenant из заголовка."""
    from src.backend.entrypoints.middlewares.request_context import (
        RequestContextMiddleware,
    )

    captured: dict[str, Any] = {}

    async def inner(scope, receive, send):  # type: ignore[no-untyped-def]
        captured["request_context"] = scope.get("state", {}).get("request_context")
        body = b"{}"
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})

    app = RequestContextMiddleware(inner)
    await _call(app, _scope(tenant_header=HEADER_TENANT))

    assert captured["request_context"].tenant_id == HEADER_TENANT
