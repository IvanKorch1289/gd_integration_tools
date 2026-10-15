"""Unit tests for rate-limit identifier/callback helpers.

Все identifier-тесты строят НАСТОЯЩИЙ ``starlette.requests.Request`` из ASGI
scope, а не ``MagicMock(spec=Request)``. Причина (regression 2026-10-15):
у настоящего ``Request`` ``user`` — property, бросающая ``AssertionError``
без AuthenticationMiddleware, тогда как у MagicMock это обычный атрибут.
Mock-тесты скрывали падение ``default_identifier`` (500 на каждом
rate-limited запросе, включая ``POST /api/v1/invocations``).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Request, status

from src.backend.core.decorators.limiting_callbacks import (
    default_callback,
    default_identifier,
)


def _make_request(
    *,
    path: str = "/api",
    headers: dict[str, str] | None = None,
    client: tuple[str, int] | None = ("10.0.0.1", 12345),
    user: object | None = None,
) -> Request:
    """Собирает настоящий Starlette Request из минимального ASGI scope."""
    raw_headers = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    scope: dict[str, object] = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": client,
        "root_path": "",
    }
    if user is not None:
        scope["user"] = user
    return Request(scope)  # type: ignore[arg-type]


class _User:
    """Минимальный объект пользователя в scope."""

    def __init__(self, user_id: str) -> None:
        self.id = user_id


@pytest.mark.asyncio
async def test_default_identifier_with_user() -> None:
    """scope['user'] с id даёт user:<id>."""
    req = _make_request(user=_User("42"))
    assert await default_identifier(req) == "user:42"


@pytest.mark.asyncio
async def test_default_identifier_with_forwarded_for() -> None:
    """X-Forwarded-For приоритетнее IP клиента."""
    req = _make_request(
        path="/api",
        headers={"x-forwarded-for": "1.2.3.4, 5.6.7.8"},
        client=("10.0.0.1", 1),
    )
    assert await default_identifier(req) == "ip:1.2.3.4:/api"


@pytest.mark.asyncio
async def test_default_identifier_fallback_ip() -> None:
    """Без user и заголовков — IP клиента."""
    req = _make_request(path="/test", client=("10.0.0.1", 1))
    assert await default_identifier(req) == "ip:10.0.0.1:/test"


@pytest.mark.asyncio
async def test_default_identifier_no_client() -> None:
    """Без client — 'unknown', без исключения."""
    req = _make_request(path="/", client=None)
    assert await default_identifier(req) == "ip:unknown:/"


@pytest.mark.asyncio
async def test_default_identifier_real_request_without_auth() -> None:
    """Regression 2026-10-15: настоящий Request без scope['user'].

    ``Request.user`` — property, которая бросает ``AssertionError``, если
    AuthenticationMiddleware не положил ``scope['user']``. Прежние тесты
    использовали ``MagicMock(spec=Request)``, где ``user`` — обычный
    атрибут, поэтому баг не проявлялся: на живом приложении rate-limit
    dependency ронял 500 на каждом запросе без установленного auth.
    """
    req = _make_request(path="/api/v1/invocations", client=("10.0.0.1", 12345))
    assert await default_identifier(req) == "ip:10.0.0.1:/api/v1/invocations"


@pytest.mark.asyncio
async def test_default_identifier_scope_user_without_id_falls_back_to_ip() -> None:
    """scope['user'] без id (SimpleUser) → fallback на IP, без падения."""

    class _NoIdUser:
        pass

    req = _make_request(path="/api", user=_NoIdUser())
    assert await default_identifier(req) == "ip:10.0.0.1:/api"


@pytest.mark.asyncio
async def test_default_callback_raises_429() -> None:
    req = _make_request()
    resp = type("R", (), {})()
    with pytest.raises(HTTPException) as exc_info:
        await default_callback(req, resp, 5500)
    assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert exc_info.value.headers["Retry-After"] == "5"
