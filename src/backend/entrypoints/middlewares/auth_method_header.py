"""Middleware, добавляющий header ``X-Auth-Method`` в response.

Полезно клиентам и observability: сразу видно, каким способом
запрос был аутентифицирован (api_key/jwt/express_jwt/...).

Метод считывается из ``request.state.auth`` (выставляется
``require_auth`` в ``auth_selector.py``). Если auth-контекст не
найден — header не добавляется.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

__all__ = ("AuthMethodHeaderMiddleware",)


class AuthMethodHeaderMiddleware(BaseHTTPMiddleware):
    """Прокидывает в response заголовок ``X-Auth-Method=<method>`` (S191 fix: opt-in).

    S191 fix: по умолчанию middleware ВЫКЛЮЧЕН — header leaks auth method
    (information disclosure для attackers — позволяет probe endpoints для
    определения auth scheme). Включение через ``settings.secure.expose_auth_method=True``.

    Default behavior: middleware registered but does NOT emit header
    unless explicitly enabled. Backward-compat: existing callers using
    AuthMethodHeader in tests need to pass ``enabled=True``.
    """

    def __init__(
        self,
        app: ASGIApp,
        header_name: str = "X-Auth-Method",
        enabled: bool = False,
    ) -> None:
        """Инициализация middleware.

        Args:
            app: ASGI-приложение.
            header_name: Имя response header.
            enabled: Включить emit header (default: False для security).
        """
        super().__init__(app)
        self._header_name = header_name
        self._enabled = enabled

    async def dispatch(self, request, call_next):
        """Метод dispatch (см. signature)."""
        response = await call_next(request)
        if not self._enabled:
            # Default off — no information disclosure
            return response

        ctx = getattr(request.state, "auth", None)
        method = getattr(ctx, "method", None)
        if method is not None:
            value = getattr(method, "value", str(method))
            response.headers[self._header_name] = value
        return response
