"""Focused tests для TenantResourceIsolationMiddleware (audit 2026-09-22 P0).

Покрывает: pass-through ветки (non-http, safe method, no match, no checker),
fail-closed deny (no tenant, not_owned), canonical BaseError rendering,
tenant resolution priority (header > state).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from src.backend.core.errors import NotFoundError
from src.backend.entrypoints.middlewares.tenant_resource_isolation import (
    DEFAULT_PATTERNS,
    TenantResourceIsolationMiddleware,
)


def _make_scope(
    path: str = "/api/v1/orders/42",
    method: str = "GET",
    *,
    tenant_header: str | None = None,
    state_tenant: str | None = None,
    scope_type: str = "http",
) -> dict[str, Any]:
    """Собирает ASGI scope для теста."""
    headers: list[tuple[bytes, bytes]] = []
    if tenant_header is not None:
        headers.append((b"x-tenant-id", tenant_header.encode("latin-1")))
    scope: dict[str, Any] = {
        "type": scope_type,
        "path": path,
        "method": method,
        "headers": headers,
        "state": {},
    }
    if state_tenant is not None:
        scope["state"]["tenant_id"] = state_tenant
    return scope


class _Downstream:
    """Фиксирует факт вызова downstream app."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.called = True


class _ResponseCollector:
    """Собирает ASGI send-события для assertions."""

    def __init__(self) -> None:
        self.start: dict[str, Any] | None = None
        self.body = b""

    async def __call__(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.start = message
        elif message["type"] == "http.response.body":
            self.body += message.get("body", b"")

    @property
    def status(self) -> int:
        assert self.start is not None, "response.start не получен"
        return self.start["status"]

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.body)


def _noop_receive() -> Any:
    async def _receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return _receive


async def _noop_send(message: dict[str, Any]) -> None:
    pass


Checker = Callable[..., Awaitable[bool]]


def _owned_checker(owned: bool, calls: list[tuple[str, str]] | None = None) -> Checker:
    """Checker-заглушка: возвращает owned, фиксирует (resource_id, tenant_id)."""

    async def _check(resource_id: str, tenant_id: str) -> bool:
        if calls is not None:
            calls.append((resource_id, tenant_id))
        return owned

    return _check


# --- Pass-through ветки ------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_http_scope_passthrough() -> None:
    """websocket/lifespan scope → downstream без проверок."""
    downstream = _Downstream()
    mw = TenantResourceIsolationMiddleware(downstream)
    mw.register_ownership_checker("order", _owned_checker(False))
    await mw(_make_scope(scope_type="websocket"), _noop_receive(), _noop_send)
    assert downstream.called


@pytest.mark.unit
@pytest.mark.asyncio
async def test_safe_method_passthrough() -> None:
    """POST (не в GET/PUT/PATCH/DELETE) → downstream без проверок."""
    downstream = _Downstream()
    mw = TenantResourceIsolationMiddleware(downstream)
    mw.register_ownership_checker("order", _owned_checker(False))
    await mw(_make_scope(method="POST"), _noop_receive(), _noop_send)
    assert downstream.called


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_pattern_match_passthrough() -> None:
    """URL вне resource-паттернов → downstream без проверок."""
    downstream = _Downstream()
    mw = TenantResourceIsolationMiddleware(downstream)
    mw.register_ownership_checker("order", _owned_checker(False))
    await mw(_make_scope(path="/api/v1/health"), _noop_receive(), _noop_send)
    assert downstream.called


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_checker_passthrough() -> None:
    """Resource-URL без зарегистрированного checker'а → pass-through."""
    downstream = _Downstream()
    mw = TenantResourceIsolationMiddleware(downstream)
    await mw(_make_scope(), _noop_receive(), _noop_send)
    assert downstream.called


# --- Enforcement: fail-closed ------------------------------------------- #


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_tenant_deny_403_checker_not_called() -> None:
    """Нет header и state tenant → 403, checker НЕ вызывается (fail-closed)."""
    downstream = _Downstream()
    mw = TenantResourceIsolationMiddleware(downstream)
    calls: list[tuple[str, str]] = []
    mw.register_ownership_checker("order", _owned_checker(True, calls))
    collector = _ResponseCollector()
    await mw(_make_scope(), _noop_receive(), collector)
    assert not downstream.called
    assert calls == []
    assert collector.status == 403
    assert collector.payload["hasErrors"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_not_owned_deny_403() -> None:
    """Checker вернул False → 403, downstream НЕ вызывается."""
    downstream = _Downstream()
    mw = TenantResourceIsolationMiddleware(downstream)
    calls: list[tuple[str, str]] = []
    mw.register_ownership_checker("order", _owned_checker(False, calls))
    collector = _ResponseCollector()
    await mw(_make_scope(tenant_header="t1"), _noop_receive(), collector)
    assert not downstream.called
    assert calls == [("42", "t1")]
    assert collector.status == 403


@pytest.mark.unit
@pytest.mark.asyncio
async def test_owned_pass_through() -> None:
    """Checker вернул True → downstream вызывается."""
    downstream = _Downstream()
    mw = TenantResourceIsolationMiddleware(downstream)
    mw.register_ownership_checker("order", _owned_checker(True))
    await mw(_make_scope(tenant_header="t1"), _noop_receive(), _noop_send)
    assert downstream.called


@pytest.mark.unit
@pytest.mark.asyncio
async def test_checker_raises_not_found_canonical_404() -> None:
    """Checker raised NotFoundError → 404 с canonical to_dict contract."""

    async def _missing(resource_id: str, tenant_id: str) -> bool:
        raise NotFoundError(message="order not found")

    downstream = _Downstream()
    mw = TenantResourceIsolationMiddleware(downstream)
    mw.register_ownership_checker("order", _missing)
    collector = _ResponseCollector()
    await mw(_make_scope(tenant_header="t1"), _noop_receive(), collector)
    assert not downstream.called
    assert collector.status == 404
    payload = collector.payload
    assert payload["hasErrors"] is True
    assert payload["error_type"] == "NotFoundError"
    assert payload["message"] == "order not found"


# --- Tenant resolution: header > state ----------------------------------- #


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tenant_from_state_fallback() -> None:
    """Нет header, но есть state['tenant_id'] (auth) → проверка по нему."""
    downstream = _Downstream()
    mw = TenantResourceIsolationMiddleware(downstream)
    calls: list[tuple[str, str]] = []
    mw.register_ownership_checker("order", _owned_checker(True, calls))
    await mw(_make_scope(state_tenant="t-state"), _noop_receive(), _noop_send)
    assert downstream.called
    assert calls == [("42", "t-state")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tenant_header_priority_over_state() -> None:
    """Header X-Tenant-ID имеет приоритет над state (семантика TenantMiddleware)."""
    downstream = _Downstream()
    mw = TenantResourceIsolationMiddleware(downstream)
    calls: list[tuple[str, str]] = []
    mw.register_ownership_checker("order", _owned_checker(True, calls))
    await mw(
        _make_scope(tenant_header="t-header", state_tenant="t-state"),
        _noop_receive(),
        _noop_send,
    )
    assert downstream.called
    assert calls == [("42", "t-header")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_tenant_header_deny_fail_closed() -> None:
    """Пустой X-Tenant-ID header → идентичности нет → 403 (fail-closed)."""
    downstream = _Downstream()
    mw = TenantResourceIsolationMiddleware(downstream)
    calls: list[tuple[str, str]] = []
    mw.register_ownership_checker("order", _owned_checker(True, calls))
    collector = _ResponseCollector()
    await mw(
        _make_scope(tenant_header="", state_tenant="t-state"),
        _noop_receive(),
        collector,
    )
    assert not downstream.called
    assert calls == []
    assert collector.status == 403


# --- Patterns / registry -------------------------------------------------- #


@pytest.mark.unit
def test_default_patterns_match_resource_urls() -> None:
    """DEFAULT_PATTERNS распознают resource-style URL всех covered типов."""
    mw = TenantResourceIsolationMiddleware(_Downstream())
    cases = {
        "/api/v1/orders/42": ("order", "42"),
        "/api/v2/users/abc": ("user", "abc"),
        "/api/v1/files/f-1": ("file", "f-1"),
        "/api/v1/tenants/t-9": ("tenant", "t-9"),
        "/api/v1/accounts/a-1": ("account", "a-1"),
        "/api/v1/documents/d-7": ("document", "d-7"),
    }
    for path, expected in cases.items():
        assert mw._match(path) == expected, path
    # Вложенный ресурс (не leaf) не должен матчиться.
    assert mw._match("/api/v1/orders/42/items") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_custom_patterns_override_defaults() -> None:
    """Кастомные patterns заменяют DEFAULT_PATTERNS."""
    from src.backend.entrypoints.middlewares.tenant_resource_isolation import (
        ResourcePattern,
    )

    downstream = _Downstream()
    custom = (
        ResourcePattern.compile(
            r"/custom/things/(?P<thing_id>[^/]+)$", "thing", "thing_id"
        ),
    )
    mw = TenantResourceIsolationMiddleware(downstream, patterns=custom)
    assert mw._match("/custom/things/x1") == ("thing", "x1")
    # Дефолтные паттерны больше не активны.
    assert mw._match("/api/v1/orders/42") is None


@pytest.mark.unit
def test_register_ownership_checker_overrides() -> None:
    """Повторная регистрация checker'а на тот же resource_type заменяет его."""
    mw = TenantResourceIsolationMiddleware(_Downstream())
    first = _owned_checker(False)
    second = _owned_checker(True)
    mw.register_ownership_checker("order", first)
    mw.register_ownership_checker("order", second)
    assert len(DEFAULT_PATTERNS) > 0
    assert mw._checkers["order"] is second
