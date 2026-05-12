"""ASGI middleware авторизации FastMCP HTTP transport (Wave D.4).

Проверяет:

* ``Authorization: Bearer <jwt>`` через ``_verify_jwt`` из
  :mod:`entrypoints.api.dependencies.auth_selector` (Track C JWT);
* либо ``X-API-Key`` через ``_verify_api_key`` оттуда же.

При успехе вызов передаётся внутрь ASGI app FastMCP.

Capability ``mcp.tool.call`` проверяется здесь на уровне корня (без
требования scope) — детальная проверка по tool-name выполняется внутри
:func:`_register_single_tool` в момент диспатча action'а.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

__all__ = ("McpAuthMiddleware",)


class _DummyHeadersRequest:
    """Минимальный shim под :func:`_verify_jwt` (ожидает ``request.headers``)."""

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


async def _verify(scope: dict[str, Any]) -> bool:
    """Возвращает True, если запрос успешно прошёл API_KEY или JWT auth."""
    from src.backend.core.config.ai_2026 import mcp_settings
    from src.backend.entrypoints.api.dependencies.auth_selector import (
        _verify_api_key,
        _verify_jwt,
    )

    raw_headers = scope.get("headers") or []
    headers: dict[str, str] = {}
    for k, v in raw_headers:
        try:
            headers[k.decode("latin1").lower()] = v.decode("latin1")
        except Exception:  # noqa: BLE001
            continue

    request = _DummyHeadersRequest(headers)
    methods = [m.lower().strip() for m in (mcp_settings.auth_methods or [])]

    if "api_key" in methods and headers.get("x-api-key"):
        try:
            ctx = await _verify_api_key(request)  # type: ignore[arg-type]
            if ctx is not None:
                return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("MCP api_key verify failed: %s", exc)

    if "jwt" in methods and headers.get("authorization", "").lower().startswith(
        "bearer "
    ):
        try:
            ctx = await _verify_jwt(request)  # type: ignore[arg-type]
            if ctx is not None:
                return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("MCP jwt verify failed: %s", exc)
    return False


class McpAuthMiddleware:
    """ASGI middleware: 401 unless API_KEY/JWT прошли."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self._app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        authorized = await _verify(scope)
        if not authorized:
            await _respond_unauthorized(send)
            return
        await self._app(scope, receive, send)


async def _respond_unauthorized(
    send: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Отправляет 401 ASGI-response."""
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Bearer, ApiKey realm="mcp"'),
            ],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b'{"error":"unauthorized","reason":"mcp auth required"}',
            "more_body": False,
        }
    )
