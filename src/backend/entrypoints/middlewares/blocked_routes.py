"""Middleware для блокировки отключённых маршрутов (cycle 39, pure ASGI).

Проверяет, не совпадает ли запрашиваемый путь с одним из паттернов
в ``blocked_routes`` (runtime_state). Поддерживает glob-шаблоны
(``/api/v1/admin/*``, ``/health``). Если совпадение найдено — 403
JSON-ответ отправляется напрямую через send (без raise).

Cycle 39: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-38 (L1 middlewares).

Cycle 39 retrospective: в BaseHTTPMiddleware middleware
``raise HTTPException(...)`` полагалось на Starlette exception
handler, который конвертировал exception в JSON response. В pure
ASGI raise из ``__call__`` не имеет такого handler'а — exception
всплывает до ASGI-сервера и крашит request. Поэтому pure ASGI
версия отправляет 403 response напрямую через ``send()``.
"""

from __future__ import annotations

import fnmatch
import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.state.runtime import blocked_routes

__all__ = ("BlockedRoutesMiddleware", "blocked_routes")


def _build_403_body(detail: str) -> bytes:
    """Возвращает JSON body для 403 response.

    Pure ASGI: в отличие от BaseHTTPMiddleware, мы НЕ можем полагаться
    на JSONResponse — отправляем JSON body напрямую.
    """
    return json.dumps({"detail": detail}).encode("utf-8")


class BlockedRoutesMiddleware:
    """Pure ASGI middleware для блокировки отключённых маршрутов.

    Поведение:
    1. Извлекает ``scope['path']`` (ASGI-аналог ``request.url.path``).
    2. Проверяет каждый паттерн в ``blocked_routes`` (glob matching).
    3. При совпадении — отправляет 403 JSON response напрямую через
       ``send()`` (НЕ raise, т.к. в pure ASGI raise не обрабатывается).
    4. Иначе — пробрасывает downstream-приложению.

    Pure ASGI: O(1) памяти на запрос (нет body-buffering), корректная
    работа со streaming, headers не блокируются.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope (``websocket`` / ``lifespan``) пробрасывается
        downstream-приложению без проверки.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Проверяем blocked patterns.
        for pattern in blocked_routes:
            if fnmatch.fnmatch(path, pattern):
                # 403 response напрямую через send (НЕ raise — pure ASGI).
                await self._send_403(send, detail="Route is disabled")
                return

        # Path не blocked — пробрасываем downstream.
        await self.app(scope, receive, send)

    @staticmethod
    async def _send_403(send: Send, *, detail: str) -> None:
        """Отправляет 403 JSON response через send (cycle 39 helper)."""
        body = _build_403_body(detail)
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )
