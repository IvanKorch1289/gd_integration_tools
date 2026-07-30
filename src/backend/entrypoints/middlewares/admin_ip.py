from __future__ import annotations

import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from src.backend.core.config.settings import settings
from src.backend.core.security.ip_restriction_store import get_ip_restriction_store

__all__ = ("IPRestrictionMiddleware",)


class IPRestrictionMiddleware(BaseHTTPMiddleware):
    """Middleware для проверки IP-адреса пользователя.

    Поддерживает:
    * глобальные административные роуты (``secure.admin_ips`` / ``admin_routes``);
    * per-route IP-ограничения из :class:`IPRestrictionStore`;
    * runtime hot-reload через store (без рестарта приложения).
    """

    def __init__(self, app: ASGIApp):
        """Инициализирует middleware.

:param app: значение app."""
        from re import compile

        from src.backend.dsl.codec.converters import convert_pattern

        super().__init__(app)
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

    async def dispatch(self, request: Request, call_next):
        """Process admin IP restriction.

        Returns:
            :class:`JSONResponse` со ``status_code=403`` если IP не разрешён,
            иначе результат ``call_next``.
        """
        path = request.url.path
        client_ip = request.client.host if request.client else None

        if not self._store.is_allowed(path, client_ip):
            return JSONResponse(
                status_code=403,
                content={"detail": "Доступ запрещен для вашего IP-адреса"},
            )

        return await call_next(request)

    def _is_admin_route(self, path: str) -> bool:
        """Проверяет, относится ли путь к административным маршрутам."""
        return any(pattern.match(path) for pattern in self._compiled_patterns)
