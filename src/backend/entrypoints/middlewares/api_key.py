"""APIKeyMiddleware — pure ASGI (cycle 47).

Middleware для проверки API-ключа в заголовках запросов.

Обеспечивает:
- Валидацию API-ключа для защищенных маршрутов
- Исключение определенных маршрутов из проверки
- Гибкую настройку через конфигурацию приложения

Cycle 47: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-46 (L1 middlewares).

M-1 dedup: если AuthRequiredMiddleware уже аутентифицировал запрос
(state.auth установлен) — пропускаем повторную валидацию.

Cycle 47 critical: dedup с AuthRequiredMiddleware.
В BaseHTTPMiddleware версии state.auth читался в dispatch. В pure
ASGI state.auth живёт в scope['state']['auth'] — нужно читать
оттуда (для совместимости с FastAPI request.state.auth алиасом).
"""

from __future__ import annotations

import json
import re
from re import compile

from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.core.config.settings import settings
from src.backend.dsl.codec.converters import convert_pattern

__all__ = ("APIKeyMiddleware",)


class APIKeyMiddleware:
    """Pure ASGI middleware для проверки API-ключа (cycle 47).

    M-1 (Sprint 16 Wave 5, deduplication): если AuthRequiredMiddleware
    уже аутентифицировал запрос — пропускаем повторную валидацию.
    AuthRequiredMiddleware (V7 defense-in-depth) пробует все 7 методов
    включая API_KEY, поэтому при установленном request.state.auth
    вторая проверка избыточна (см. ADR-стек авторизации).
    """

    def __init__(self, app: ASGIApp) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
        """
        self.app = app
        # Компилируем шаблоны исключений из настроек.
        self.compiled_patterns: list[re.Pattern] = [
            compile(convert_pattern(pattern))
            for pattern in settings.secure.routes_without_api_key
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope (``websocket`` / ``lifespan``) пробрасывается
        downstream без API key check.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # M-1 dedup: если AuthRequiredMiddleware уже аутентифицировал —
        # пропускаем. state.auth хранится в scope['state']['auth'] (pure ASGI)
        # или в request.state.auth (FastAPI алиас). Проверяем обе.
        state = scope.get("state", {}) if "state" in scope else {}
        auth = state.get("auth") if isinstance(state, dict) else None
        if auth is not None:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Пропускаем для excluded routes.
        if self._is_excluded_route(path):
            await self.app(scope, receive, send)
            return

        # Извлекаем X-API-Key header (case-insensitive).
        api_key = _get_header_value(scope, b"x-api-key")
        if api_key is None:
            await self._send_401(
                send, detail="Требуется API-ключ"
            )
            return

        # Валидируем API-ключ через constant-time compare.
        import secrets as _secrets

        if not _secrets.compare_digest(api_key, settings.secure.api_key):
            await self._send_401(send, detail="Неверный API-ключ")
            return

        # API-ключ валиден → пробрасываем downstream.
        await self.app(scope, receive, send)

    @staticmethod
    async def _send_401(send: Send, *, detail: str) -> None:
        """Отправляет 401 JSON response через send (no-raise, cycle 39)."""
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    def _is_excluded_route(self, path: str) -> bool:
        """Проверяет, исключен ли маршрут из проверки API-ключа."""
        return any(pattern.match(path) for pattern in self.compiled_patterns)


def _get_header_value(scope: Scope, name: bytes) -> str | None:
    """Извлекает header из ASGI scope по lowercase bytes-имени."""
    for header_name, header_value in scope.get("headers", []):
        if header_name == name:
            try:
                return header_value.decode("latin-1")
            except UnicodeDecodeError:
                return None
    return None
