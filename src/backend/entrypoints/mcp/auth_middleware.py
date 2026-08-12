"""ASGI middleware авторизации FastMCP HTTP transport (Wave D.4).

Проверяет:

* ``Authorization: Bearer <jwt>`` через public :func:`verify_request`
  из :mod:`core.auth.auth_selector` (Track C JWT);
* либо ``X-API-Key`` через тот же public API.

D-AUDIT-10101 fix (cycle 101, SECURITY-P1-004): заменён импорт
приватных ``_verify_api_key`` / ``_verify_jwt`` (S93 W3 encapsulation
violation) на public ``verify_request``. Создаём Starlette Request
из ASGI scope и передаём в public API.

При успехе вызов передаётся внутрь ASGI app FastMCP.

Capability ``mcp.tool.call`` проверяется здесь на уровне корня (без
требования scope) — детальная проверка по tool-name выполняется внутри
:func:`_register_single_tool` в момент диспатча action'а.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.requests import Request

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = ("McpAuthMiddleware",)


async def _verify(scope: dict[str, Any]) -> bool:
    """Возвращает True, если запрос успешно прошёл auth через public API.

    D-AUDIT-10101 fix (cycle 101): использует public ``verify_request``
    (из core.auth.auth_selector) вместо импорта приватных
    ``_verify_api_key`` / ``_verify_jwt``. Public API iterates через
    enabled methods (api_key, jwt, basic, ...) и возвращает первый
    successful AuthContext — для MCP не нужны explicit dispatch на
    method.
    """
    from src.backend.core.auth.auth_selector import verify_request
    from src.backend.core.config.ai_stack import mcp_settings

    # Build minimal ASGI receive/send для Starlette Request.
    # Для auth verification нужен только headers — body не читается.
    async def _receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _send(_: dict[str, Any]) -> None:
        return None  # no-op; мы не отправляем response

    try:
        request = Request(scope, receive=_receive)
    except Exception as exc:
        # D-AUDIT-10101: не 'except Exception: _' (silent), а narrow +
        # structured log. Request construction может fail только при
        # malformed scope (TypeError/ValueError).
        logger.warning(
            "MCP _verify: failed to construct Request from scope "
            "(exc_type=%s exc_msg=%s)",
            type(exc).__name__,
            exc,
        )
        return False

    methods = [m.lower().strip() for m in (mcp_settings.auth_methods or [])]
    if not methods:
        # No methods configured → fail-CLOSED (default secure).
        return False

    try:
        ctx = await verify_request(request, methods=methods)
    except Exception as exc:
        logger.debug("MCP verify_request failed: %s", exc)
        return False

    return ctx is not None


class McpAuthMiddleware:
    """ASGI middleware: 401 unless API_KEY/JWT прошли."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        """Инициализирует middleware.

        :param app: значение app.
        """
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
        },
    )
    await send(
        {
            "type": "http.response.body",
            "body": b'{"error":"unauthorized","reason":"mcp auth required"}',
            "more_body": False,
        },
    )
