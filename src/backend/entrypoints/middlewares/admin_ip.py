"""Middleware для проверки IP-адреса пользователя (cycle 41, pure ASGI).

Поддерживает:
* глобальные административные роуты (``secure.admin_ips`` / ``admin_routes``);
* per-route IP-ограничения из :class:`IPRestrictionStore`;
* runtime hot-reload через store (без рестарта приложения).

Cycle 41: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-40 (L1 middlewares).

Cycle 41: использует no-raise pattern (cycle 39 lesson) — 403
отправляется через send напрямую, не через raise HTTPException.
"""

from __future__ import annotations

import json
import re
from re import compile

from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.core.config.settings import settings
from src.backend.core.security.ip_restriction_store import get_ip_restriction_store
from src.backend.dsl.codec.converters import convert_pattern

__all__ = ("IPRestrictionMiddleware",)


class IPRestrictionMiddleware:
    """Pure ASGI middleware: IP-restriction check (cycle 41).

    Поведение:
    1. Извлекает ``scope['path']`` и ``scope['client']`` (ASGI-аналоги
       ``request.url.path`` и ``request.client.host``).
    2. Проверяет через :class:`IPRestrictionStore.is_allowed`.
    3. Если IP не разрешён → 403 JSON response через send (no-raise).
    4. Иначе → пробрасывает downstream-приложению.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
        """
        self.app = app
        self._store = get_ip_restriction_store()
        # Инициализируем store начальными значениями из settings.
        self._store.update_admin(
            admin_ips=set(settings.secure.admin_ips),
            admin_routes=list(settings.secure.admin_routes),
        )
        self._compiled_patterns: list[re.Pattern] = [
            compile(convert_pattern(pattern))
            for pattern in settings.secure.admin_routes
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope (``websocket`` / ``lifespan``) пробрасывается
        downstream-приложению без IP-проверки.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        client = scope.get("client")
        client_ip = client[0] if client else None

        if not self._store.is_allowed(path, client_ip):
            await self._send_403(send)
            return

        # IP allowed → пробрасываем downstream.
        await self.app(scope, receive, send)

    @staticmethod
    async def _send_403(send: Send) -> None:
        """Отправляет 403 JSON response через send (cycle 39/40 lesson)."""
        body_bytes = json.dumps(
            {"detail": "Доступ запрещен для вашего IP-адреса"}
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_bytes)).encode("latin-1")),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body_bytes,
            }
        )

    def _is_admin_route(self, path: str) -> bool:
        """Проверяет, относится ли путь к административным маршрутам."""
        return any(pattern.match(path) for pattern in self._compiled_patterns)
